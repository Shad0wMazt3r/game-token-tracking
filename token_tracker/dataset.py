"""Local capture, labeling, session-level splits and YOLO pose training."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import time

def pose_label(class_id,box,keypoint,width,height,visibility=2):
    x,y,w,h=box; px,py=keypoint
    if type(class_id) is not int or class_id<0 or width<=0 or height<=0 or visibility not in (0,1,2):
        raise ValueError("Invalid label metadata")
    if not all(math.isfinite(v) for v in (x,y,w,h,px,py)) or w<=0 or h<=0 or x<0 or y<0 or x+w>width or y+h>height:
        raise ValueError("Box must fit inside the image")
    if not 0<=px<=width or not 0<=py<=height:
        raise ValueError("Keypoint must fit inside the image")
    return f"{class_id} {(x+w/2)/width:.8f} {(y+h/2)/height:.8f} {w/width:.8f} {h/height:.8f} {px/width:.8f} {py/height:.8f} {visibility}"

def validate_label(line,class_count):
    fields=line.split()
    if len(fields)!=8: raise ValueError("Expected one 3D base keypoint per object")
    try:
        class_id=int(fields[0]); visibility=int(fields[7]); values=list(map(float,fields[1:7]))
    except ValueError: raise ValueError("Invalid pose label")
    if not 0<=class_id<class_count or visibility not in (0,1,2) or not all(math.isfinite(v) and 0<=v<=1 for v in values):
        raise ValueError("Invalid pose class, coordinates or visibility")
    cx,cy,w,h,px,py=values
    if w<=0 or h<=0 or cx-w/2 < -1e-7 or cx+w/2 > 1+1e-7 or cy-h/2 < -1e-7 or cy+h/2 > 1+1e-7:
        raise ValueError("Invalid normalized bounding box")

def split_dataset(source,destination,names,seed=42):
    source,destination=Path(source),Path(destination)
    if destination.exists(): raise ValueError("Output exists; choose a new directory")
    if len(names)!=len(set(names)) or not names or any(not n for n in names):
        raise ValueError("Unique nonempty class names required")
    sessions=sorted(p for p in source.iterdir() if p.is_dir() and (p/"manifest.json").exists())
    if len(sessions)<3: raise ValueError("Record and label at least three independent sessions for train/val/test")
    random.Random(seed).shuffle(sessions)
    test_count=max(1,len(sessions)//5); val_count=max(1,len(sessions)//5)
    groups={"test":sessions[:test_count],"val":sessions[test_count:test_count+val_count],"train":sessions[test_count+val_count:]}
    plan=[]; hashes={}; counts={}; class_counts={split:[0]*len(names) for split in groups}
    for split,group in groups.items():
        counts[split]=0
        for session in group:
            manifest=json.loads((session/"manifest.json").read_text())
            if manifest.get("class_names") != names: raise ValueError("Session class names differ: "+session.name)
            images=sorted((session/"images").glob("*.jpg"))
            for image in images:
                label=session/"labels"/(image.stem+".txt")
                # Missing labels are unlabeled, not negative examples.
                if not label.exists(): continue
                for line in label.read_text().splitlines():
                    if line.strip():
                        validate_label(line,len(names)); class_counts[split][int(line.split()[0])]+=1
                digest=hashlib.sha256(image.read_bytes()).hexdigest()
                if digest in hashes and hashes[digest]!=split:
                    raise ValueError("Duplicate image across splits")
                hashes[digest]=split
                plan.append((split,session.name+"__"+image.name,image,label)); counts[split]+=1
    if any(count==0 for count in counts.values()): raise ValueError("Each split needs at least one explicitly labeled image")
    if any(count==0 for count in class_counts["train"]): raise ValueError("Every class needs training annotations")
    for split,name,image,label in plan:
        image_dir=destination/"images"/split; label_dir=destination/"labels"/split
        image_dir.mkdir(parents=True,exist_ok=True); label_dir.mkdir(parents=True,exist_ok=True)
        shutil.copy2(image,image_dir/name); shutil.copy2(label,label_dir/(Path(name).stem+".txt"))
    # JSON is valid YAML; avoids another dependency.
    config=dict(path=destination.resolve().as_posix(),train="images/train",val="images/val",test="images/test",kpt_shape=[1,3],flip_idx=[0],names=dict(enumerate(names)))
    (destination/"dataset.yaml").write_text(json.dumps(config,indent=2))
    report=dict(seed=seed,session_splits={split:[p.name for p in group] for split,group in groups.items()},images=counts,objects=class_counts)
    (destination/"split-report.json").write_text(json.dumps(report,indent=2))
    return report

def capture(args):
    import cv2
    from .capture import Camera
    output=Path(args.output)
    if output.exists(): raise ValueError("Session output already exists")
    if len(set(args.sources))!=len(args.sources) or not 1<=len(args.sources)<=2:
        raise ValueError("Choose one or two distinct webcams")
    if not 1<=len(args.classes)<=8 or len(set(args.classes))!=len(args.classes):
        raise ValueError("Choose one to eight unique piece class names")
    if args.interval<=0 or args.duration<=0: raise ValueError("Positive duration and interval required")
    output.mkdir(parents=True); (output/"images").mkdir(); (output/"labels").mkdir()
    manifest=dict(class_names=args.classes,cameras=args.sources,created_at=time.time(),samples=[])
    cameras={}; start=time.monotonic(); due=start; index=0
    try:
        for source in args.sources: cameras[source]=Camera(source)
        while time.monotonic()-start<args.duration:
            snapshots={source:camera.snapshot() for source,camera in cameras.items()}
            if time.monotonic()>=due:
                for source,item in snapshots.items():
                    if item is None: continue
                    frame,sequence,timestamp=item
                    if time.monotonic()-timestamp>0.3: continue
                    name=f"camera{source}_{index:06d}.jpg"
                    if not cv2.imwrite(str(output/"images"/name),frame): raise RuntimeError("Failed to save frame")
                    manifest["samples"].append(dict(image=name,camera=source,time_seconds=timestamp-start,sequence=sequence))
                index+=1; due=time.monotonic()+args.interval
            for source,item in snapshots.items():
                if item is not None: cv2.imshow("capture camera "+str(source)+" | Esc exits",item[0])
            if cv2.waitKey(1)&255==27: break
            time.sleep(0.01)
    finally:
        (output/"manifest.json").write_text(json.dumps(manifest,indent=2))
        for camera in cameras.values(): camera.close()
        cv2.destroyAllWindows()

def annotate(args):
    import cv2
    session=Path(args.session); manifest=json.loads((session/"manifest.json").read_text()); names=manifest["class_names"]
    if not 1<=len(names)<=8: raise ValueError("Labeler supports one to eight classes")
    window="label: 1-8 class, B box, click base, Enter add, V visibility, U undo, C cancel, S save, N skip, Esc quit"
    cv2.namedWindow(window,cv2.WINDOW_AUTOSIZE)
    active=0; visibility=2
    try:
        for image_path in sorted((session/"images").glob("*.jpg")):
            output=session/"labels"/(image_path.stem+".txt")
            if output.exists() and not args.relabel: continue
            image=cv2.imread(str(image_path))
            if image is None: raise ValueError("Cannot read "+str(image_path))
            height,width=image.shape[:2]; labels=[]; box=None; keypoint=None
            def click(event,x,y,flags,param):
                nonlocal keypoint
                if event==cv2.EVENT_LBUTTONDOWN and box is not None: keypoint=(x,y)
            cv2.setMouseCallback(window,click)
            while True:
                view=image.copy()
                status=f"{image_path.name} | {active+1}: {names[active]} | visibility {visibility} | {len(labels)} saved objects"
                cv2.putText(view,status,(10,25),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,255,255),1)
                for label in labels:
                    fields=label.split(); cid=int(fields[0]); cx,cy,w,h,px,py=map(float,fields[1:7])
                    a=(int((cx-w/2)*width),int((cy-h/2)*height)); b=(int((cx+w/2)*width),int((cy+h/2)*height))
                    cv2.rectangle(view,a,b,(0,180,0),1); cv2.circle(view,(int(px*width),int(py*height)),3,(0,180,0),-1)
                    cv2.putText(view,names[cid],a,cv2.FONT_HERSHEY_SIMPLEX,0.4,(0,180,0),1)
                if box:
                    x,y,w,h=box; cv2.rectangle(view,(x,y),(x+w,y+h),(0,255,0),1)
                if keypoint: cv2.circle(view,keypoint,4,(0,0,255),-1)
                cv2.imshow(window,view); key=cv2.waitKey(20)&255
                if key==27: return
                if ord('1')<=key<=ord('8') and key-ord('1')<len(names): active=key-ord('1')
                if key==ord('b'):
                    candidate=cv2.selectROI(window,image,fromCenter=False,showCrosshair=True)
                    if candidate[2]>0 and candidate[3]>0: box=tuple(map(int,candidate)); keypoint=None
                    cv2.setMouseCallback(window,click)
                if key==ord('v'): visibility=1 if visibility==2 else 2
                if key==13 and box and keypoint:
                    labels.append(pose_label(active,box,keypoint,width,height,visibility)); box=None; keypoint=None
                if key==ord('u') and labels: labels.pop()
                if key==ord('c'): box=None; keypoint=None
                if key==ord('n'): break
                if key==ord('s'):
                    if box: print("Press Enter to add the pending object or C to cancel"); continue
                    output.write_text("\n".join(labels)+( "\n" if labels else "")); break
    finally: cv2.destroyAllWindows()

def main():
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("capture"); p.add_argument("--sources",nargs="+",type=int,default=[0]); p.add_argument("--output",required=True); p.add_argument("--classes",nargs="+",required=True); p.add_argument("--interval",type=float,default=0.5); p.add_argument("--duration",type=float,default=120)
    p=sub.add_parser("annotate"); p.add_argument("session"); p.add_argument("--relabel",action="store_true")
    p=sub.add_parser("split"); p.add_argument("source"); p.add_argument("output"); p.add_argument("--classes",nargs="+",required=True); p.add_argument("--seed",type=int,default=42)
    p=sub.add_parser("train"); p.add_argument("dataset"); p.add_argument("--model",default="yolo11n-pose.pt"); p.add_argument("--epochs",type=int,default=60); p.add_argument("--imgsz",type=int,default=960); p.add_argument("--device",default="cpu"); p.add_argument("--seed",type=int,default=42)
    args=parser.parse_args()
    if args.command=="capture": capture(args)
    elif args.command=="annotate": annotate(args)
    elif args.command=="split": print(json.dumps(split_dataset(args.source,args.output,args.classes,args.seed),indent=2))
    elif args.command=="train":
        from ultralytics import YOLO
        YOLO(args.model).train(data=args.dataset,epochs=args.epochs,imgsz=args.imgsz,device=args.device,seed=args.seed,deterministic=True,fliplr=0.0,flipud=0.0,workers=0)

if __name__=="__main__": main()
