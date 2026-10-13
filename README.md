# Game Token Tracking

Local tabletop miniature tracking using ordinary, unmounted consumer webcams beside a table. Physical positions are mapped into a configurable square grid and sent to manually paired Foundry VTT tokens.

## Implemented

- One/two-camera latest-frame capture and shared board coordinates.
- Full-board or partial-view calibration from visible grid intersections.
- Custom YOLO pose adapter: one base-center keypoint and a distinct class per physical piece.
- Conservative multi-view fusion, geometry sensitivity checks and stable movement events.
- Local image capture, interactive labeling, session-level dataset splits and training commands.
- Foundry v13 module with a GM control panel, persistent per-scene pairings and localhost bridge.
- Move-trial evaluation plus Python/JavaScript tests.

**No trained miniature weights are included.** The code is a prototype, not a validated arbitrary-mini recognizer. Live camera/Foundry testing and measured acceptance results remain to be done.

## Install

Python 3.10+; Node 22 is needed only for JavaScript tests.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[yolo]"
```

For CPU-only bridge/testing work, install `-e .` without the optional YOLO dependencies.

## Start here

1. [Foundry setup](docs/foundry-setup.md): test a token movement without a camera.
2. [Prototype walkthrough](docs/prototype-walkthrough.md): capture footage, label pieces, train and calibrate both views.
3. Edit [examples/session.json](examples/session.json), then run:

```powershell
python -m token_tracker.session examples/session.json --log moves.jsonl
```

## Tests

```powershell
python -m unittest discover -s tests -v
node --test tests/foundry/core.test.mjs tests/foundry/module.test.mjs
```

## Current limits

This first model assigns one class per visually distinct piece; adding pieces requires retraining. Identical pieces cannot reliably keep separate identities through complete occlusion. Two cameras improve visibility but do not make hidden bases observable. The sensitivity estimate describes planar projection geometry, not learned keypoint accuracy. Capture-to-Foundry latency and the 95% grid-square goal have not been measured.

The Foundry module targets v13 and one GM browser. Other versions, game systems, hosted HTTPS setups and arbitrary real minis need evaluation.
