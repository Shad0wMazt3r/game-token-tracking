"""Replay synthetic board observations without OpenCV, cameras, or model weights."""
import argparse
import json
import os
from pathlib import Path
import time
from .pipeline import replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--columns", type=int, required=True)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--bridge")
    parser.add_argument("--scene-id")
    parser.add_argument("--output")
    parser.add_argument("--realtime", action="store_true", help="Preserve frame intervals when publishing to Foundry")
    args = parser.parse_args()
    frames = [json.loads(line) for line in Path(args.input).read_text().splitlines() if line.strip()]
    # Validate the complete trace before sending any external movement.
    results = list(replay(frames, args.columns, args.rows))
    publisher = None
    if args.bridge:
        from .bridge import BridgePublisher
        publisher = BridgePublisher(args.bridge, os.environ.get("TOKEN_TRACKER_KEY"), args.scene_id, args.columns, args.rows)
    output = []
    started = time.monotonic()
    first = frames[0]["time"] if frames else 0
    for frame, result in zip(frames, results):
        if args.realtime:
            remaining = frame["time"] - first - (time.monotonic() - started)
            while remaining > 0:
                time.sleep(min(remaining, 0.1))
                remaining = frame["time"] - first - (time.monotonic() - started)
        for event in result["events"]:
            if publisher:
                from .state import Movement
                publisher.publish(Movement(event["piece_id"], event["column"], event["row"], event["observed_at"]))
            output.append(json.dumps(event))
            print(output[-1], flush=True)
    if args.output:
        Path(args.output).write_text("\n".join(output) + ("\n" if output else ""))


if __name__ == "__main__":
    main()
