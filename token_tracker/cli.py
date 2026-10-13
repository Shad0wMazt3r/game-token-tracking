"""Calibrate from a webcam/video, then emit stable movements as JSON lines."""
import argparse
from dataclasses import asdict
import json
import os
import time
import cv2
from .calibration import Calibration
from .state import Stabilizer

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    calibration = sub.add_parser("calibrate")
    calibration.add_argument("--columns", type=int, required=True)
    calibration.add_argument("--rows", type=int, required=True)
    calibration.add_argument("--output", default="calibration.json")
    calibration.add_argument("--points",help="JSON list of board coordinates to click, for partial camera coverage")
    tracking = sub.add_parser("track")
    tracking.add_argument("--calibration", required=True)
    tracking.add_argument("--weights", required=True)
    tracking.add_argument("--settle-ms", type=float, default=200)
    tracking.add_argument("--bridge", help="Optional localhost Foundry bridge URL")
    tracking.add_argument("--scene-id", help="Required with --bridge")
    for p in (calibration, tracking):
        p.add_argument("--source", default="0", help="Webcam index or video path")
        p.add_argument("--width",type=int,default=1280)
        p.add_argument("--height",type=int,default=720)
    args = parser.parse_args()
    is_camera = args.source.isdecimal()
    source = int(args.source) if is_camera else args.source
    publisher = None
    if args.command == "track" and args.bridge:
        from .bridge import BridgePublisher, AsyncBridgePublisher
        configured = Calibration.load(args.calibration)
        sender = BridgePublisher(args.bridge,os.environ.get("TOKEN_TRACKER_KEY"),args.scene_id,configured.columns,configured.rows)
        publisher = AsyncBridgePublisher(sender)
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        if publisher:
            publisher.close()
        raise SystemExit("Cannot open camera/video")
    if is_camera:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH,args.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT,args.height)
    try:
        if args.command == "calibrate":
            ok, frame = capture.read()
            if not ok:
                raise SystemExit("Cannot read calibration frame")
            points = []
            if args.points:
                with open(args.points) as stream: targets=json.load(stream)
            else:
                targets=[[0,0],[args.columns,0],[args.columns,args.rows],[0,args.rows]]
            if len(targets)<4: raise ValueError("At least four board reference points required")
            def click(event,x,y,flags,param):
                if event == cv2.EVENT_LBUTTONDOWN and len(points) < len(targets):
                    points.append((x,y))
            cv2.namedWindow("calibrate: TL TR BR BL; Enter saves; R resets")
            window = "calibrate: TL TR BR BL; Enter saves; R resets"
            cv2.setMouseCallback(window, click)
            while True:
                view = frame.copy()
                for i,p in enumerate(points):
                    cv2.circle(view,p,5,(0,255,0),-1)
                    cv2.putText(view,str(targets[i]),p,cv2.FONT_HERSHEY_SIMPLEX,0.6,(0,255,0),2)
                if len(points)<len(targets):
                    cv2.putText(view,"Click board coordinate "+str(targets[len(points)]),(10,25),cv2.FONT_HERSHEY_SIMPLEX,0.6,(0,255,255),1)
                cv2.imshow(window,view)
                key = cv2.waitKey(20) & 255
                if key == 27:
                    break
                if key in (ord('r'),ord('R')):
                    points.clear()
                if key == 13 and len(points) == len(targets):
                    size=(frame.shape[1],frame.shape[0])
                    calibrated=(Calibration.from_points(points,targets,args.columns,args.rows,size) if args.points else Calibration.from_corners(points,args.columns,args.rows,size))
                    calibrated.save(args.output)
                    break
        else:
            from .detector import YoloBaseDetector
            board = Calibration.load(args.calibration)
            detector = YoloBaseDetector(args.weights)
            state = Stabilizer(board.columns,board.rows,args.settle_ms/1000)
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not is_camera and fps <= 0:
                raise SystemExit("Video must provide a valid frame rate")
            frame_index = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if board.image_size and board.image_size != (frame.shape[1],frame.shape[0]):
                    raise ValueError("Input resolution differs from calibration")
                timestamp = time.monotonic() if is_camera else frame_index/fps
                frame_index += 1
                seen = set()
                for observation in detector.detect(frame):
                    seen.add(observation.piece_id)
                    x,y = board.project(observation.x,observation.y)
                    event = state.observe(observation.piece_id,x,y,timestamp)
                    if event:
                        print(json.dumps(asdict(event)),flush=True)
                        if publisher:
                            publisher.publish(event)
                    location = (int(observation.x),int(observation.y))
                    cv2.circle(frame,location,4,(0,255,0),-1)
                    cv2.putText(frame,f"{observation.piece_id}: {x:.1f},{y:.1f}",location,cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,255,0),1)
                for piece_id in list(state.pending):
                    if piece_id not in seen:
                        state.missing(piece_id)
                cv2.imshow("tracking; Esc exits",frame)
                if cv2.waitKey(1) & 255 == 27:
                    break
    finally:
        if publisher:
            publisher.close()
        capture.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
