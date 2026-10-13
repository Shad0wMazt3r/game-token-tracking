"""One/two-camera live tracking with shared board coordinates."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import time
import cv2
from .capture import Camera
from .calibration import Calibration
from .detector import YoloBaseDetector
from .fusion import BoardObservation,fuse
from .state import Stabilizer

def load_config(filename):
    path=Path(filename).resolve()
    data=json.loads(path.read_text())
    cameras=data.get("cameras",[])
    if not 1 <= len(cameras) <= 2 or len({c["id"] for c in cameras}) != len(cameras):
        raise ValueError("Configure one or two uniquely named cameras")
    if len({c["source"] for c in cameras}) != len(cameras):
        raise ValueError("Camera sources must be different")
    for camera in cameras:
        if type(camera["source"]) is not int or camera["source"] < 0:
            raise ValueError("Live sources must be webcam indices")
        camera["calibration"]=str((path.parent/camera["calibration"]).resolve())
    data["weights"]=str((path.parent/data["weights"]).resolve())
    boards={c["id"]:Calibration.load(c["calibration"]) for c in cameras}
    dimensions={(b.columns,b.rows) for b in boards.values()}
    if len(dimensions) != 1: raise ValueError("Every camera must share board dimensions")
    return data,boards

def draw_grid(frame,board):
    import numpy as np
    inverse=np.linalg.inv(board.matrix)
    def pixel(x,y):
        p=inverse@np.array([x,y,1.0])
        if abs(p[2])<1e-8: return None
        x,y=p[:2]/p[2]
        if not np.isfinite([x,y]).all() or abs(x)>100000 or abs(y)>100000: return None
        return int(x),int(y)
    for column in range(board.columns+1):
        a,b=pixel(column,0),pixel(column,board.rows)
        if a and b: cv2.line(frame,a,b,(80,80,80),1)
    for row in range(board.rows+1):
        a,b=pixel(0,row),pixel(board.columns,row)
        if a and b: cv2.line(frame,a,b,(80,80,80),1)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--log",help="Optional movement/debug JSONL log")
    args=parser.parse_args()
    config,boards=load_config(args.config)
    board=next(iter(boards.values()))
    detector=YoloBaseDetector(config["weights"],image_size=config.get("imgsz",960),device=config.get("device"))
    state=Stabilizer(board.columns,board.rows,config.get("settle_ms",200)/1000,
                     config.get("tolerance_cells",0.12),config.get("max_gap_ms",500)/1000)
    publisher=None; cameras={}; seen_sequences={}; latest={}; processed={}; paused=False; overlay=True
    log=open(args.log,"a",encoding="utf8") if args.log else None
    try:
        if config.get("bridge"):
            from .bridge import BridgePublisher,AsyncBridgePublisher
            publisher=AsyncBridgePublisher(BridgePublisher(config["bridge"],os.environ.get("TOKEN_TRACKER_KEY"),config.get("scene_id"),board.columns,board.rows))
        for camera in config["cameras"]:
            cameras[camera["id"]]=Camera(camera["source"],camera.get("width",1280),camera.get("height",720))
        while True:
            frames={}; start=time.monotonic()
            for name,camera in cameras.items():
                snapshot=camera.snapshot()
                if snapshot is None: continue
                frame,sequence,timestamp=snapshot; frames[name]=frame
                if sequence==seen_sequences.get(name): continue
                seen_sequences[name]=sequence
                projected=[]
                if not paused and start-timestamp <= config.get("max_age_ms",300)/1000:
                    for observation in detector.detect(frame):
                        calibration=boards[name]
                        if calibration.image_size and calibration.image_size != (frame.shape[1],frame.shape[0]):
                            raise ValueError("Camera resolution differs from calibration: "+name)
                        try:
                            x,y=calibration.project(observation.x,observation.y)
                        except ValueError:
                            continue
                        uncertainty=calibration.uncertainty(observation.x,observation.y)
                        projected.append(BoardObservation(observation.piece_id,x,y,observation.confidence,uncertainty,name,timestamp))
                        cv2.circle(frame,(int(observation.x),int(observation.y)),4,(0,255,0),-1)
                        cv2.putText(frame,f"{observation.piece_id}: {x:.1f},{y:.1f} geometry~{uncertainty:.2f}",(int(observation.x),int(observation.y)),cv2.FONT_HERSHEY_SIMPLEX,0.45,(0,255,0),1)
                latest[name]=projected
            now=time.monotonic()
            positions,ambiguous=fuse([o for view in latest.values() for o in view],now,board.columns,board.rows,
                max_age=config.get("max_age_ms",300)/1000,
                max_uncertainty=config.get("max_uncertainty_cells",0.35),
                disagreement=config.get("disagreement_cells",0.4))
            if paused: positions={}
            for piece,(x,y,timestamp) in positions.items():
                if timestamp <= processed.get(piece,-1): continue
                processed[piece]=timestamp
                event=state.observe(piece,x,y,timestamp)
                if event:
                    record=asdict(event)|{"emitted_at":now,"observation_age_ms":(now-event.observed_at)*1000}
                    print(json.dumps(record),flush=True)
                    if log: log.write(json.dumps(record)+"\n"); log.flush()
                    if publisher: publisher.publish(event)
            for piece in list(state.pending):
                if piece not in positions: state.missing(piece)
            for name,frame in frames.items():
                if overlay: draw_grid(frame,boards[name])
                text=("PAUSED" if paused else "TRACKING")+f" | {len(positions)} pieces | ambiguous: {','.join(sorted(ambiguous))}"
                cv2.putText(frame,text,(10,25),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,255,255),1)
                cv2.imshow(name+" | Space pause, G grid, R resync, Esc exit",frame)
            key=cv2.waitKey(1)&255
            if key in (27,ord('q')): break
            if key==32:
                paused=not paused; state.pending.clear(); latest.clear(); processed.clear()
            if key==ord('g'): overlay=not overlay
            if key==ord('r'): state.pending.clear(); state.confirmed.clear(); latest.clear(); processed.clear()
            if not frames: time.sleep(0.01)
    finally:
        for camera in cameras.values(): camera.close()
        if publisher: publisher.close()
        if log: log.close()
        cv2.destroyAllWindows()

if __name__=="__main__": main()
