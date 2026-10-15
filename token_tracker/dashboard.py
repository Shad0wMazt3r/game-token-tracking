"""Local control surface and real bridge; cameras and YOLO are loaded on demand."""
import argparse
from collections import deque
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit
from .bridge import BridgeState, MAX_BODY, make_server
from .pipeline import Pipeline

ASSETS = Path(__file__).with_name("web")


class Runtime:
    def __init__(self, state, directory):
        self.state = state
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.cameras = {}
        self.boards = {}
        self.previews = {}
        self.mode = "simulation"
        self.running = False
        self.error = ""
        self.history = deque(maxlen=80)
        self.diagnostics = {}
        self.pipeline = Pipeline(state.columns, state.rows)
        self.worker = None
        self.halt = threading.Event()
        self.detector = None
        self.inventory = ["goblin_1", "knight_1", "wizard_1"]

    def status(self):
        with self.lock:
            return dict(mode=self.mode, running=self.running, error=self.error,
                        scene_id=self.state.scene_id, columns=self.state.columns, rows=self.state.rows,
                        session=self.state.session, sequence=self.state.sequence,
                        pieces=list(self.inventory), cameras=[dict(id=name, calibrated=name in self.boards,
                            error=camera.error, **self.diagnostics.get(name, {})) for name, camera in self.cameras.items()],
                        confirmed={k: list(v) for k, v in self.pipeline.state.confirmed.items()},
                        history=list(self.history), diagnostics=dict(self.diagnostics))

    def publish(self, event, source):
        packet = {key: event[key] for key in ("piece_id", "column", "row")}
        packet.update(scene_id=self.state.scene_id, columns=self.state.columns, rows=self.state.rows)
        sequence = self.state.publish(packet)
        self.history.appendleft(packet | {"sequence": sequence, "source": source, "accepted_at": time.time()})
        return sequence

    def control(self, data):
        action = data.get("action")
        with self.lock:
            if action == "pause":
                self.running = False
                self.pipeline.state.pending.clear()
                self.pipeline.processed.clear()
            elif action == "resync":
                self.pipeline.reset()
            elif action == "mode":
                if data.get("mode") not in ("simulation", "camera"):
                    raise ValueError("Unknown mode")
                self.running = False
                self.mode = data["mode"]
                self.pipeline.reset()
            elif action == "start":
                if self.mode == "camera":
                    if not self.cameras or set(self.cameras) != set(self.boards) or self.detector is None:
                        raise ValueError("Open cameras, calibrate each view, and load custom weights first")
                self.error = ""
                self.running = True
            elif action == "inventory":
                if self.mode != "simulation":
                    raise ValueError("Edit inventory in simulation mode; camera inventory comes from the model")
                pieces = data.get("pieces")
                if (not isinstance(pieces, list) or not 1 <= len(pieces) <= 64 or
                    any(not isinstance(p, str) or not p.strip() or len(p) > 128 for p in pieces) or
                    len(set(pieces)) != len(pieces)):
                    raise ValueError("Use 1-64 unique nonempty piece IDs, at most 128 characters each")
                self.running = False
                self.inventory = pieces
                self.pipeline.reset()
            else:
                raise ValueError("Unknown control action")
        return self.status()

    def move(self, data):
        with self.lock:
            if self.mode != "simulation" or not self.running:
                raise ValueError("Start simulation before moving a piece")
            if data.get("piece_id") not in self.inventory:
                raise ValueError("Unknown inventory piece")
            sequence = self.publish(data, "simulation")
            self.pipeline.state.confirmed[data["piece_id"]] = (data["column"], data["row"])
            return {"sequence": sequence, "status": "bridge accepted"}

    def open_cameras(self, data):
        from .capture import Camera
        cameras = data.get("cameras")
        if (not isinstance(cameras, list) or not 1 <= len(cameras) <= 2 or
            any(not isinstance(c, dict) or type(c.get("source")) is not int or not 0 <= c["source"] <= 32 for c in cameras) or
            len({c["source"] for c in cameras}) != len(cameras)):
            raise ValueError("Choose one or two distinct webcam indices between 0 and 32")
        with self.lock:
            self.running = False
            self.pipeline.reset()
            for camera in self.cameras.values():
                camera.close()
            self.cameras.clear()
            self.boards.clear()
            self.previews.clear()
            self.diagnostics.clear()
            try:
                for index, config in enumerate(cameras):
                    self.cameras[str(index)] = Camera(config["source"], 1280, 720)
            except Exception:
                for camera in self.cameras.values():
                    camera.close()
                self.cameras.clear()
                raise
            if self.worker is None:
                self.worker = threading.Thread(target=self._loop, daemon=True)
                self.worker.start()
        return self.status()

    def frame(self, camera_id, freeze=False):
        import cv2
        with self.lock:
            camera = self.cameras.get(camera_id)
            if camera is None:
                raise ValueError("Open this camera first")
            snapshot = camera.snapshot()
            if snapshot is None:
                raise ValueError("Camera has not delivered a frame")
            frame, sequence, timestamp = snapshot
            if time.monotonic() - timestamp > 1:
                raise ValueError("Camera frame is stale; reconnect the camera")
            if freeze:
                self.running = False
                self.pipeline.state.pending.clear()
                self.pipeline.processed.clear()
                self.previews[camera_id] = frame.copy()
            elif camera_id in self.boards:
                from .session import draw_grid
                draw_grid(frame, self.boards[camera_id])
            ok, encoded = cv2.imencode(".jpg", frame)
            if not ok:
                raise ValueError("Cannot encode preview")
            return encoded.tobytes()

    def calibrate(self, data):
        from .calibration import Calibration
        with self.lock:
            name = str(data.get("camera"))
            frame = self.previews.get(name)
            if frame is None:
                raise ValueError("Freeze a calibration frame first")
            image = data.get("image_points")
            board = data.get("board_points")
            if not isinstance(image, list) or not isinstance(board, list) or not 4 <= len(image) <= 32:
                raise ValueError("Use 4-32 image/board reference pairs")
            calibrated = Calibration.from_points(image, board, self.state.columns, self.state.rows,
                                                 (frame.shape[1], frame.shape[0]))
            self.running = False
            self.pipeline.reset()
            self.boards[name] = calibrated
            calibrated.save(self.directory / ("calibration-" + name + ".json"))
            return {"residual_cells": calibrated.residual_cells, "image_size": calibrated.image_size}

    def load_weights(self, data):
        from .detector import YoloBaseDetector
        # Local authenticated operator may choose weights; there is no remote upload endpoint.
        path = Path(data.get("path", "")).expanduser().resolve()
        if path.suffix != ".pt" or not path.is_file():
            raise ValueError("Choose an existing local custom .pt weights file")
        with self.lock:
            self.running = False
            self.pipeline.reset()
            self.detector = None
            detector = YoloBaseDetector(str(path), device="cpu")
            self.detector = detector
            self.inventory = list(detector.model.names.values())
        return self.status()

    def _loop(self):
        latest = {}
        sequences = {}
        while not self.halt.wait(0.01):
            with self.lock:
                if not self.running or self.mode != "camera":
                    latest.clear()
                    sequences.clear()
                    continue
                try:
                    from .fusion import BoardObservation
                    for name, camera in self.cameras.items():
                        snapshot = camera.snapshot()
                        if snapshot is None:
                            continue
                        frame, sequence, timestamp = snapshot
                        age = time.monotonic() - timestamp
                        self.diagnostics[name] = {"age_ms": round(age * 1000), "width": frame.shape[1], "height": frame.shape[0]}
                        if sequences.get(name) == sequence:
                            continue
                        sequences[name] = sequence
                        latest[name] = []
                        if age > 0.3:
                            continue
                        board = self.boards[name]
                        if board.image_size != (frame.shape[1], frame.shape[0]):
                            raise ValueError("Camera resolution changed; freeze a frame and recalibrate")
                        started = time.monotonic()
                        for observation in self.detector.detect(frame):
                            x, y = board.project(observation.x, observation.y)
                            latest[name].append(BoardObservation(observation.piece_id, x, y, observation.confidence,
                                                                board.uncertainty(observation.x, observation.y), name, timestamp))
                        self.diagnostics[name]["inference_ms"] = round((time.monotonic() - started) * 1000)
                    result = self.pipeline.step(time.monotonic(), [o for values in latest.values() for o in values])
                    self.diagnostics["fusion"] = {"usable": result["usable"], "ambiguous": result["ambiguous"]}
                    for event in result["events"]:
                        self.publish(event, "camera")
                except Exception as error:
                    self.error = str(error)
                    self.running = False
                    self.pipeline.state.pending.clear()
                    self.pipeline.processed.clear()

    def close(self):
        self.halt.set()
        if self.worker:
            self.worker.join(timeout=5)
        with self.lock:
            for camera in self.cameras.values():
                camera.close()


def dashboard_server(state, token, origin, port=8765, directory="dashboard-data"):
    server = make_server(state, token, origin, port)
    runtime = Runtime(state, directory)
    base = server.RequestHandlerClass
    actual_port = server.server_port
    local_origins = {"http://127.0.0.1:" + str(actual_port), "http://localhost:" + str(actual_port)}

    class Handler(base):
        def valid_host(self):
            return self.headers.get("Host") in {"127.0.0.1:" + str(actual_port), "localhost:" + str(actual_port)}

        def allowed_origin(self):
            return self.valid_host() and (super().allowed_origin() or self.headers.get("Origin") in local_origins)

        def raw(self, data, content_type):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            try:
                self.wfile.write(data)
            except ConnectionError:
                pass  # Browser navigation can close a preview response early.

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {"error": "Host denied"})
            parsed = urlsplit(self.path)
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if parsed.path in assets:
                name, content_type = assets[parsed.path]
                return self.raw((ASSETS / name).read_bytes(), content_type)
            if parsed.path.startswith("/api/"):
                if not self.authorized():
                    return self.reply(403, {"error": "Unauthorized"})
                try:
                    if parsed.path == "/api/status":
                        return self.reply(200, runtime.status())
                    if parsed.path == "/api/frame":
                        name = parse_qs(parsed.query).get("camera", ["0"])[0]
                        return self.raw(runtime.frame(name), "image/jpeg")
                    return self.reply(404, {"error": "Not found"})
                except (ValueError, ImportError) as error:
                    return self.reply(400, {"error": str(error)})
            return super().do_GET()

        def do_POST(self):
            if not self.valid_host():
                return self.reply(403, {"error": "Host denied"})
            if not self.path.startswith("/api/"):
                return super().do_POST()
            if not self.authorized():
                return self.reply(403, {"error": "Unauthorized"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    return self.reply(413, {"error": "Invalid body size"})
                self.connection.settimeout(2)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Object required")
                actions = {"/api/control": runtime.control, "/api/move": runtime.move,
                           "/api/cameras": runtime.open_cameras, "/api/calibrate": runtime.calibrate,
                           "/api/weights": runtime.load_weights}
                if self.path == "/api/freeze":
                    return self.raw(runtime.frame(str(data.get("camera", "0")), freeze=True), "image/jpeg")
                if self.path not in actions:
                    return self.reply(404, {"error": "Not found"})
                return self.reply(200, actions[self.path](data))
            except (ValueError, TypeError, KeyError, ImportError, OSError, TimeoutError, RuntimeError) as error:
                return self.reply(400, {"error": str(error)})

    server.RequestHandlerClass = Handler
    server.runtime = runtime
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--columns", type=int, default=12)
    parser.add_argument("--rows", type=int, default=8)
    parser.add_argument("--origin", default="http://localhost:30000")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", default="dashboard-data")
    args = parser.parse_args()
    if not 1 <= args.columns <= 64 or not 1 <= args.rows <= 64:
        parser.error("Dashboard board dimensions must be between 1 and 64")
    token = os.environ.get("TOKEN_TRACKER_KEY") or secrets.token_urlsafe(32)
    server = dashboard_server(BridgeState(args.scene_id, args.columns, args.rows), token, args.origin, args.port, args.data)
    print("Dashboard: http://127.0.0.1:" + str(server.server_port) + "/#key=" + token, flush=True)
    print("Foundry bridge key: " + token, flush=True)
    print("Use this server instead of a separate bridge process. Ctrl+C stops it.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.runtime.close()
        server.server_close()


if __name__ == "__main__":
    main()
