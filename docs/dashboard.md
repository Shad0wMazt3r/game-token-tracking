# Local dashboard and simulation

[Documentation home](../README.md) · [Foundry setup](foundry-setup.md) · [Architecture](architecture.md)

The dashboard is an actual local Python application, with a browser interface served by the same process as the bridge. Simulation does not need OpenCV, YOLO weights, or a webcam. Camera mode loads those dependencies only when requested.

## Start a session

Install the project as described in the README, then run from the repository root:

```powershell
python -m token_tracker.dashboard --scene-id YOUR_SCENE_ID --columns 12 --rows 8 --origin http://localhost:30000
```

Use the real Foundry scene ID for synchronization, or `--scene-id demo` for a standalone simulation. Open the URL printed in the terminal. Its fragment contains the local bridge key; the app removes it from the address bar and retains it in that tab's session storage. Do not share the startup URL or key. The dashboard serves only on loopback.

**Run this instead of a separate bridge process.** Both default to port 8765. The same bridge URL/key go into the Foundry module. The `--origin` must exactly match the GM browser's Foundry origin.

## Simulate without a model

1. Start the Foundry module first if you want token updates; explicitly pair the matching piece IDs.
2. In the dashboard choose Simulation, edit the inventory if needed, then Start simulation.
3. Select a piece and click a grid square, or drag an inventory piece onto it.
4. Inspect the latest confirmed board position and recent bridge acceptance history.
5. In Foundry inspect Applied movements to verify that its token document update resolved.

Simulation publishes genuine movement events. It deliberately bypasses model inference and stability filtering; the replay tool tests those board-space decisions separately. Pause prevents further dashboard simulation moves. It does not stop a separate external tracker publishing to the same bridge.

Recent history is bounded to 80 dashboard-originated acceptances and lives in process memory. Export recent JSON downloads that history, not the evaluator's prediction format. External CLI publishers still work, but are not added to the dashboard's history or confirmed-board display.

## Camera workflow

1. Choose Cameras. Enter one or two webcam indices, then Open cameras.
2. Select a view and Freeze for calibration. This stops tracking and freezes an actual camera frame.
3. Enter ordered board intersections, then click their corresponding image locations. Coordinates use full-board grid units, even for partial views. The default list is the board's four corners.
4. Save calibration. Repeat for every view and check unused intersections independently.
5. Enter the full path to a trusted local custom `.pt` weights file; Load weights. The initial dashboard uses CPU inference. The inventory is replaced by model class names.
6. Start tracking. Review frame age, inference duration, usable observations, ambiguity, and confirmed positions.

Calibration records are saved under `dashboard-data/` by default (`--data` changes the directory). After restarting, reopen cameras and load weights again. Compatible calibrations restore automatically when a fresh frame arrives. Camera handles, inventory edits, and model selection are not restored. Existing CLI/session workflows remain available for saved configuration and GPU inference.

### Calibration reuse and recovery

Reuse requires an unambiguous stable physical camera identity, the same board columns/rows, and the exact **actual** frame width/height. Requested 1280×720 settings are not evidence of the delivered size. Records are keyed by camera identity rather than view/index, so changing the enumeration order does not transfer calibration to a different camera. Tracking remains paused after reopening.

Currently automatic identity discovery supports Linux USB V4L2 cameras that expose a serial number, vendor/product IDs, interface number, and video-node index in sysfs. Windows, macOS, cameras without serials, and ambiguous duplicate identities conservatively require calibration each time cameras reopen; they can still be calibrated and tracked during the current session. Model names and enumeration indices are deliberately not treated as physical identities. Serial numbers must be unique and trustworthy; cloned/bogus device serials cannot establish identity.

The camera diagnostics explain whether a calibration was restored, is waiting for a fresh frame, or needs replacement. Missing, malformed, unsupported-version, invalid-matrix, and incompatible records leave that view uncalibrated. Old `calibration-<view>.json` files lack identity metadata and are never automatically imported. For recovery, select the view, **Freeze for calibration**, choose reference points, and **Save calibration**. Saving replaces that camera's versioned record atomically when stable identity is available; otherwise it is session-only. Keep the same `--data` directory across runs.

Identity and resolution cannot establish whether the camera or tabletop moved, or whether lens zoom/cropping changed. Verify the projected grid against unused intersections before starting; explicitly freeze and recalibrate whenever geometry changes, even if the saved record is accepted.

Resync clears confirmed and pending tracker positions. Camera mode emits positions again after fresh stable observations. In Simulation, place pieces again. A removed or hidden physical piece does not delete a digital token.

The UI requests 1280×720; actual size is used for calibration and checked before inference. Disconnects cause stale observations to expire; reopen cameras explicitly to recover. Reopening cameras rechecks saved calibrations against physical identity, board dimensions, and fresh image resolution. A resolution change during tracking stops the tracker and invalidates that view until recalibration. Camera/model failures stop tracking and appear in the interface.

## Replay repeatable failures

```powershell
python -m token_tracker.replay examples/replay.jsonl --columns 12 --rows 8 --output replay-moves.jsonl
```

Each JSONL frame contains `time` and a complete `observations` list. Observations contain `piece_id`, board-space `x`/`y`, `confidence`, projection `uncertainty`, `camera`, and `timestamp`. Empty snapshots simulate missing detections. Future, stale, off-board, duplicate-camera, and conflicting observations exercise rejection and recovery behavior.

Replay uses the same Pipeline class as dashboard camera mode. The older `token_tracker.session` still has its own orchestration; its fusion and stabilization primitives are shared, but replay is not a complete camera/video emulator or projection test.

To publish replay through the real bridge after starting Foundry:

```powershell
$env:TOKEN_TRACKER_KEY = "YOUR_BRIDGE_TOKEN"
python -m token_tracker.replay examples/replay.jsonl --columns 12 --rows 8 --bridge http://127.0.0.1:8765 --scene-id YOUR_SCENE_ID --realtime
```

The complete trace is validated before publication. Without `--realtime`, publication runs as fast as possible and later positions may supersede earlier ones before the browser polls. Replay timestamps are synthetic; they cannot measure real capture-to-Foundry latency.

## Browser and integration checks

```powershell
python -m pip install -e ".[test]"
python -m playwright install chromium
python tests/browser_checks.py
```

The browser checks run the real local dashboard and real module JavaScript against a simulated Foundry host, including actual authenticated HTTP delivery to the service. They cover desktop/mobile layout, simulation, pause, invalid inventory, missing camera setup, pairing, applied token updates, stop, removal, panel reopening, and connection loss/recovery. Calibration click order and scaled-image coordinates are checked with a synthetic preview and a stubbed save endpoint; calibration math is covered separately by the Python suite. Screenshots are written to ignored `test-results/`.

This is not live Foundry testing. Verify the module in the team's licensed v13 world and game system before claiming compatibility. No camera accuracy, trained weights, automatic camera reconnect, or complete end-to-end latency measurement is supplied by this UI.
