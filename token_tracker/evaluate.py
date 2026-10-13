"""Score held-out move trials. Timestamps must share a monotonic clock."""
import argparse
import json
import math
from pathlib import Path
import numpy as np

def evaluate(trials,predictions,window=3.0):
    if window<=0: raise ValueError("Positive matching window required")
    trials=sorted(trials,key=lambda t:t["settled_at"])
    predictions=sorted(predictions,key=lambda p:p["emitted_at"])
    for row in trials:
        if not math.isfinite(row["settled_at"]): raise ValueError("Invalid trial timestamp")
    for row in predictions:
        if not math.isfinite(row["emitted_at"]): raise ValueError("Invalid prediction timestamp")
    used=set(); outcomes=[]; latencies=[]
    for index,trial in enumerate(trials):
        end=trial["settled_at"]+window
        following=[t["settled_at"] for t in trials[index+1:] if t["piece_id"]==trial["piece_id"]]
        if following: end=min(end,following[0])
        candidates=[(i,p) for i,p in enumerate(predictions) if i not in used and p["piece_id"]==trial["piece_id"] and trial["settled_at"]<=p["emitted_at"]<end]
        # First emitted update after resting is the one the GM experiences.
        if not candidates:
            outcomes.append(dict(piece_id=trial["piece_id"],result="miss")); continue
        i,p=candidates[0]; used.add(i)
        correct=(p["column"],p["row"])==(trial["column"],trial["row"])
        latency=(p["emitted_at"]-trial["settled_at"])*1000
        outcomes.append(dict(piece_id=trial["piece_id"],result="correct" if correct else "wrong",latency_ms=latency))
        if correct: latencies.append(latency)
    count=len(trials); correct=sum(o["result"]=="correct" for o in outcomes)
    return dict(trials=count,correct=correct,accuracy=correct/count if count else None,
                wrong=sum(o["result"]=="wrong" for o in outcomes),missed=sum(o["result"]=="miss" for o in outcomes),
                extra_updates=len(predictions)-len(used),
                p50_correct_emission_ms=float(np.percentile(latencies,50)) if latencies else None,
                p95_correct_emission_ms=float(np.percentile(latencies,95)) if latencies else None,
                note="Latency ends at tracker emission, not Foundry update acknowledgement",outcomes=outcomes)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("truth"); parser.add_argument("predictions"); parser.add_argument("--window",type=float,default=3); parser.add_argument("--output")
    args=parser.parse_args()
    def read(path): return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    result=evaluate(read(args.truth),read(args.predictions),args.window)
    text=json.dumps(result,indent=2); print(text)
    if args.output: Path(args.output).write_text(text)

if __name__=="__main__": main()
