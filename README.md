# Game Token Tracking

Local Python prototype for tabletop minis viewed by ordinary, unmounted webcams beside a table.

## Current scope

Single-camera calibration and inference, configurable square grid, base-center pose keypoints, movement stabilization, and JSON movement events. Includes a localhost Foundry v13 bridge and GM module. No trained weights, multi-camera identity fusion, or measured accuracy claim yet. This is a fixed-piece-set experiment, not an arbitrary-mini recognizer.

## Setup

Python 3.10+; create a virtual environment, then run:

```powershell
python -m pip install -e ".[yolo]"
python -m token_tracker.cli calibrate --source 0 --columns 12 --rows 8
python -m token_tracker.cli track --source 0 --calibration calibration.json --weights best.pt
python -m unittest discover -s tests
```

Calibration uses a frozen camera frame: click the board corners in TL, TR, BR, BL order; Enter saves, R resets, Esc exits. A video path may replace the camera index. Do not move the camera after calibration.

## Model contract

Train a YOLO pose model with one keypoint per mini: the center of its base on the board plane. The first experiment uses one visual class per distinct physical piece. Multiple detections with the same class are withheld as ambiguous. Identical pieces require another identity strategy. Generic pretrained human-pose weights do not satisfy this contract.

Annotate representative footage from the actual angled placements, including rotations, overlaps, and hands. Use a pose dataset YAML with `kpt_shape: [1, 3]`, `flip_idx: [0]`, and your class names. A starting training command:

```powershell
yolo pose train model=yolo11n-pose.pt data=dataset.yaml epochs=60 imgsz=960
```

Fine-tuning needs actual images and labels. Split by recording session to avoid adjacent-frame leakage. Keep fully occluded points labeled consistently; never assume a predicted hidden keypoint is trustworthy without testing.

## Geometry and reliability

Homography maps board-plane points only. Body bounding-box centers are not suitable for oblique views. Edge-on views amplify position error; distortion correction and additional board reference points are future work. Each eventual camera needs its own calibration into the same board coordinates.

Stable updates require a 200 ms window with observations close to the anchor and no large observation gap. Missing and off-board observations clear pending movement but preserve confirmed positions. Off-board inactivity and persistent Foundry mappings are not implemented yet. Events identify the physical class, column, row, and observation timestamp.

## Next steps

1. Capture and label actual tabletop footage; train base-keypoint weights.
2. Evaluate grid accuracy, identity swaps, and end-to-end latency on held-out sessions.
3. Add independently calibrated second-camera observations and ambiguity handling.
4. Validate the Foundry integration in a live world; add reusable visual profiles.

## Foundry VTT

See [Foundry setup](docs/foundry-setup.md) for installation, per-scene pairing macros, localhost bridge configuration, and a manual movement test that needs no camera or trained model. Targets v13; live-world compatibility has not yet been verified.
