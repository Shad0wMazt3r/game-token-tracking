import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from token_tracker.bridge import BridgeState, BridgePublisher
from token_tracker.dashboard import dashboard_server
from token_tracker.state import Movement

KEY = "test-token-at-least-16-characters"


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.server = dashboard_server(BridgeState("scene", 12, 8), KEY, "http://localhost:30000", 0, self.directory.name)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.runtime.close()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, path, data=None, key=KEY, **headers):
        req = Request(self.url + path, data=json.dumps(data).encode() if data is not None else None,
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", **headers})
        return urlopen(req, timeout=3)

    def call(self, path, data=None):
        with self.request(path, data) as response:
            return json.load(response)

    def test_assets_and_security_headers(self):
        for path in ("/", "/style.css", "/app.js"):
            with self.request(path, key="") as response:
                self.assertEqual(response.status, 200)
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                self.assertNotIn(KEY, response.read().decode())

    def test_auth_origin_host_and_path_boundaries(self):
        for path, key, headers in (("/api/status", "bad", {}), ("/api/status", KEY, {"Origin": "https://evil.example"}),
                                   ("/api/status", KEY, {"Host": "evil.example"}), ("/", KEY, {"Host": "evil.example"})):
            with self.assertRaises(HTTPError) as error:
                self.request(path, key=key, **headers)
            self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            self.request("/../../pyproject.toml")
        self.assertEqual(error.exception.code, 404)

    def test_same_origin_browser_posts_allowed(self):
        with self.request("/api/control", {"action": "start"}, Origin=self.url) as response:
            self.assertTrue(json.load(response)["running"])

    def test_start_simulate_poll_pause_and_resync(self):
        move = dict(piece_id="goblin_1", column=3, row=2)
        with self.assertRaises(HTTPError):
            self.call("/api/move", move)
        self.call("/api/control", {"action": "start"})
        self.assertEqual(self.call("/api/move", move)["sequence"], 1)
        self.assertEqual(self.call("/events")["events"][0]["column"], 3)
        status = self.call("/api/control", {"action": "pause"})
        self.assertEqual(status["confirmed"]["goblin_1"], [3, 2])
        self.assertEqual(status["history"][0]["source"], "simulation")
        self.assertEqual(self.call("/api/control", {"action": "resync"})["confirmed"], {})

    def test_reject_invalid_grid_and_unknown_piece(self):
        self.call("/api/control", {"action": "start"})
        for data in ({"piece_id":"goblin_1","column":12,"row":0}, {"piece_id":"missing","column":0,"row":0},
                     {"piece_id":"goblin_1","column":True,"row":0}):
            with self.assertRaises(HTTPError) as error:
                self.call("/api/move", data)
            self.assertEqual(error.exception.code, 400)
        self.assertEqual(self.server.runtime.state.sequence, 0)

    def test_modes_and_inventory_pause_before_changes(self):
        self.call("/api/control", {"action": "start"})
        status = self.call("/api/control", {"action": "inventory", "pieces": ["custom"]})
        self.assertFalse(status["running"])
        self.assertEqual(status["pieces"], ["custom"])
        self.call("/api/control", {"action": "mode", "mode": "camera"})
        with self.assertRaises(HTTPError):
            self.call("/api/control", {"action": "start"})
        for pieces in ([], ["x", "x"], [""], [1]):
            with self.assertRaises(HTTPError):
                self.call("/api/control", {"action": "inventory", "pieces": pieces})

    def test_existing_publisher_and_foundry_origin_remain_compatible(self):
        BridgePublisher(self.url, KEY, "scene", 12, 8).publish(Movement("goblin_1", 1, 1, 0))
        with self.request("/events", Origin="http://localhost:30000") as response:
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "http://localhost:30000")
            self.assertEqual(json.load(response)["sequence"], 1)

    def test_key_not_exposed_and_history_is_bounded(self):
        self.call("/api/control", {"action":"start"})
        for i in range(85):
            self.server.runtime.move(dict(piece_id="goblin_1", column=i % 12, row=1))
        status = self.call("/api/status")
        self.assertNotIn(KEY, json.dumps(status))
        self.assertEqual(len(status["history"]), 80)

    def test_control_bad_body_and_missing_preview(self):
        for path, data in (("/api/control", []), ("/api/control", {"action":"unknown"}),
                           ("/api/freeze", {"camera":"99"})):
            with self.assertRaises(HTTPError) as error:
                self.call(path, data)
            self.assertEqual(error.exception.code, 400)

    def test_replay_pipeline_publishes_through_real_http(self):
        from pathlib import Path
        from token_tracker.pipeline import replay
        frames = [json.loads(line) for line in (Path(__file__).parents[1] / "examples/replay.jsonl").read_text().splitlines()]
        publisher = BridgePublisher(self.url, KEY, "scene", 12, 8)
        emitted = []
        for result in replay(frames, 12, 8):
            for event in result["events"]:
                emitted.append(event)
                publisher.publish(Movement(event["piece_id"], event["column"], event["row"], event["observed_at"]))
        self.assertEqual(len(emitted), 2)
        packet = self.call("/events")
        self.assertEqual(packet["sequence"], 2)
        self.assertEqual(packet["events"][0]["column"], 4)

    def test_camera_disconnect_holds_confirmed_position(self):
        runtime = self.server.runtime
        runtime.pipeline.state.confirmed["goblin_1"] = (3, 2)
        class Camera:
            error = "Camera stopped delivering frames"
            def snapshot(self): return None
            def close(self): pass
        runtime.cameras["0"] = Camera()
        runtime.mode = "camera"
        runtime.running = True
        with patch.object(runtime.halt, "wait", side_effect=[False, True]):
            runtime._loop()
        self.assertEqual(runtime.status()["cameras"][0]["error"], Camera.error)
        self.assertEqual(runtime.status()["confirmed"]["goblin_1"], [3, 2])
        self.assertEqual(runtime.pipeline.state.pending, {})

    def test_inference_failure_and_resolution_change_stop_safely(self):
        import time
        runtime = self.server.runtime
        class Frame:
            shape = (720, 1280, 3)
        class Camera:
            error = None
            def snapshot(self): return Frame(), 1, time.monotonic()
            def close(self): pass
        class Board:
            image_size = (1280, 720)
        class Detector:
            def detect(self, frame): raise RuntimeError("Inference unavailable")
        runtime.cameras["0"] = Camera()
        runtime.detector = Detector()
        runtime.boards["0"] = Board()
        for shape, message in (((720, 1280, 3), "Inference unavailable"), ((480, 640, 3), "resolution changed")):
            with self.subTest(shape=shape):
                Frame.shape = shape
                runtime.mode = "camera"
                runtime.running = True
                runtime.pipeline.state.confirmed["goblin_1"] = (3, 2)
                with patch.object(runtime.halt, "wait", side_effect=[False, True]):
                    runtime._loop()
                self.assertFalse(runtime.running)
                self.assertIn(message, runtime.error)
                self.assertEqual(runtime.pipeline.state.confirmed["goblin_1"], (3, 2))
