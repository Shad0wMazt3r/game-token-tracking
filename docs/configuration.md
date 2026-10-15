# Configuration reference

[Documentation home](../README.md) · [Walkthrough](prototype-walkthrough.md)

Run commands from the repository root. Use [examples/session.json](../examples/session.json) as the starting file.

## Live session JSON

Paths for weights and calibration are resolved relative to the session JSON file. For a file in `examples/`, `../calibration-left.json` refers to the repository root.

| Field | Default / requirement | Meaning |
|---|---|---|
| `weights` | Required | Custom one-base-keypoint pose model |
| `cameras` | Required; one or two | Camera definitions |
| `cameras[].id` | Required, unique | Name for overlays and observations |
| `cameras[].source` | Required, distinct nonnegative integer | Webcam index; live sessions do not accept video paths |
| `cameras[].calibration` | Required | Per-camera calibration JSON |
| `cameras[].width` / `height` | 1280 / 720 | Requested capture resolution; camera may negotiate another size |
| `imgsz` | 960 | Inference image size |
| `device` | Library selection | Use `"cpu"` or an appropriate GPU selector such as `"0"` |
| `settle_ms` | 200 | Minimum stable candidate duration |
| `tolerance_cells` | 0.12 | Allowed distance from candidate anchor |
| `max_gap_ms` | 500 | Maximum observation gap before candidate resets |
| `max_age_ms` | 300 | Maximum age accepted by fusion |
| `disagreement_cells` | 0.4 | Maximum separation between usable camera observations |
| `max_uncertainty_cells` | 0.35 | Maximum projection sensitivity for a two-pixel offset |
| `bridge` | Disabled if absent/null | HTTP loopback bridge URL |
| `scene_id` | Required when publishing | Exact target Foundry scene ID |

These are prototype defaults, not validated optimal thresholds. Increasing age/gap thresholds can make slow inference appear more continuous while allowing stale evidence. Measure before tuning. Detector box and keypoint thresholds default to 0.5 and are currently adapter constructor parameters rather than session JSON fields.

For one camera remove the second entry. For vision-only testing set `"bridge": null`. The current session loader does not comprehensively validate every numeric tuning field; use finite, positive values for time limits and sensible nonnegative geometric tolerances.

## Calibration files

Calibration stores `columns`, `rows`, a 3×3 `matrix`, `image_size` as [width,height], and `residual_cells`. Use the calibration tool rather than editing the matrix.

```powershell
python -m token_tracker.cli calibrate --source 0 --columns 12 --rows 8 --width 1280 --height 720 --points examples/board-points-left.json --output calibration-left.json
```

Partial-view references are an ordered JSON list of known board intersections. Click each matching image point in that order. All cameras must use identical full-board dimensions. Camera motion, resolution changes, or changed optics require recalibration. Independently check unused grid intersections after saving.

## Bridge and environment

`TOKEN_TRACKER_KEY` is the only service secret used by the Python tools:

```powershell
$env:TOKEN_TRACKER_KEY = "YOUR_BRIDGE_TOKEN"
python -m token_tracker.bridge serve --scene-id YOUR_SCENE_ID --columns 12 --rows 8 --origin http://localhost:30000
```

A missing key in the service shell causes it to generate and print a new token. Enter that same token in Foundry and set it in the tracker/manual-move shell. The server requires at least 16 characters. Do not put keys in committed configuration or logs.

The service port defaults to 8765; `serve --port` changes it. Change the module's bridge URL and tracker configuration together. `--origin` must match the GM browser's scheme, host, and port exactly.

## Foundry settings

| Setting | Scope | Purpose |
|---|---|---|
| `bridgeURL` | Client | Loopback service address |
| `bridgeKey` | Client | Bearer token |
| `sceneId` | Client | Scene allowed to receive updates |
| `originX`, `originY` | Client | Physical board's top-left in canvas pixels |
| `pairings` | World | Scene ID → physical piece ID → placed token ID |

Use the GM panel's **Use current scene** to initialize the origin with scene padding included. For a board covering a subsection of the map, enter the subsection's top-left. The physical board and token footprint must fit in the playable scene.

## Entry points

| Command | Input / result |
|---|---|
| `python -m token_tracker.dashboard --scene-id ID` | Local dashboard with built-in bridge; defaults to a 12×8 board |
| `python -m token_tracker.replay TRACE --columns C --rows R` | Synthetic observations → repeatable movement events |
| `python -m token_tracker.cli calibrate` | Camera/video frame → calibration file |
| `python -m token_tracker.cli track` | One camera/video + weights → movements |
| `python -m token_tracker.session CONFIG --log FILE` | One/two live webcams → fused movements and JSONL |
| `python -m token_tracker.bridge serve` | Local HTTP bridge |
| `python -m token_tracker.bridge move` | Manual grid move without model |
| `python -m token_tracker.dataset capture` | Webcam images and session manifest |
| `python -m token_tracker.dataset annotate SESSION` | Boxes and base-point labels |
| `python -m token_tracker.dataset split SOURCE OUTPUT` | Session-grouped dataset |
| `python -m token_tracker.dataset train DATASET_YAML` | Fine-tune pose weights |
| `python -m token_tracker.evaluate TRUTH PREDICTIONS` | Trial score report |

Each entry point exposes `--help`. Single-source video timestamps use frame index / FPS; live-session timestamps use the local monotonic clock. Do not compare those clock domains directly.
