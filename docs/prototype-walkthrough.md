# Prototype walkthrough

## Scope

This workflow builds a fixed-set model for up to eight visually distinct physical pieces. It uses ordinary webcams placed beside the table, without mounts or markers on the pieces. Keep the cameras fixed after calibration. The board must have visible non-collinear reference points; a camera looking exactly along the board plane cannot recover stable board coordinates.

The software pipeline is implemented, but no actual miniature footage, trained weights or live Foundry acceptance measurements are included.

## 1. Check Foundry separately

Follow [Foundry setup](foundry-setup.md). After installing and enabling the module, the GM can use the **Token Tracker** button at the bottom-right of the screen:

- Use current scene to initialize scene and board origin.
- Enter the localhost bridge URL and token; Save connection.
- Select a placed token on the canvas, enter the exact physical class name, and Pair.
- Start/Stop controls tracking. Configuration and pairing changes stop it.

The panel is non-modal so you can select tokens while it is open. Macro equivalents remain in the setup guide. First send a manual move to prove the Foundry adapter works before debugging vision.

## 2. Capture independent sessions

Use a small fixed set of pieces at first. Example:

```powershell
python -m token_tracker.dataset capture --sources 0 1 --classes goblin_1 knight_1 wizard_1 --output sessions/session-a --duration 120 --interval 0.5
```

Repeat with fresh output directories session-b and session-c. Three independent sessions is the minimum to create train/validation/test splits; more sessions are preferable.

Capture pieces at different grid squares, orientations, camera distances, lighting conditions and levels of overlap. Include hands, dice, busy maps and empty boards. Use the real side-of-table placements. The tool saves JPEGs and a camera/timestamp manifest locally. Both camera views of the same session stay in the same split.

Do not flood the dataset with nearly identical frames. Start around 200–500 varied labeled frames as an experiment, then inspect failures; that range is not an accuracy guarantee.

## 3. Label boxes and base centers

```powershell
python -m token_tracker.dataset annotate sessions/session-a
```

Repeat for each session.

- Keys 1–8 select the physical piece class.
- B opens a bounding-box selection around the whole miniature.
- Click the center of the base **on the board plane**.
- Enter adds the object. Repeat for every visible piece.
- V toggles visible (2) / occluded but localizable (1).
- U removes the last added object; C cancels the pending selection.
- S explicitly saves the frame, including an empty annotation for a negative example.
- N skips a frame; Esc exits. Rerunning resumes at unannotated images.

Saved annotations are drawn in green. The keypoint is the base center, not the body center or bottom-middle of the entire silhouette. Do not invent the location of a completely hidden base. Skip frames whose objects cannot be annotated consistently. Visibility flags help describe annotations but do not make the detector's confidence a calibrated probability.

Missing labels are excluded from training, not treated as empty negative examples. The labeler does not edit existing files unless --relabel is passed.

## 4. Build and train the dataset

```powershell
python -m token_tracker.dataset split sessions datasets/minis-v1 --classes goblin_1 knight_1 wizard_1
python -m token_tracker.dataset train datasets/minis-v1/dataset.yaml --epochs 60 --imgsz 960 --device 0
```

Use --device cpu without a compatible GPU; training will be slower. Configure PyTorch appropriately for your GPU using its official installation instructions. The tool loads pretrained YOLO11 nano pose weights and fine-tunes the single-keypoint head for your labels. It does not train from random initialization.

The split tool checks label ranges, matching class names, cross-split duplicate bytes and training coverage per class. It writes a split report. A split is grouped by recording session, preventing adjacent frames and simultaneous camera views from leaking into validation/test. Different sessions can still be visually similar; keep the test recordings meaningfully independent.

Horizontal/vertical flips are disabled in the initial training recipe to avoid accidentally changing the visual identity of asymmetric pieces. The seed is fixed, but exact reproducibility also depends on library versions, hardware and drivers.

Inspect validation results with:

```powershell
yolo pose val model=runs/pose/train/weights/best.pt data=datasets/minis-v1/dataset.yaml split=test
```

The actual training output directory may be train2, train3, etc. Copy its exact best.pt path into the session configuration.

Generic human-pose weights are rejected by the runtime because they do not satisfy the one-base-keypoint contract.

## 5. Calibrate each view

For a camera seeing the whole 12-by-8 board:

```powershell
python -m token_tracker.cli calibrate --source 0 --columns 12 --rows 8 --output calibration-left.json
```

Click TL, TR, BR, BL and press Enter. R resets the points.

For partial coverage, provide known board coordinates:

```powershell
python -m token_tracker.cli calibrate --source 0 --columns 12 --rows 8 --points examples/board-points-left.json --output calibration-left.json
python -m token_tracker.cli calibrate --source 1 --columns 12 --rows 8 --points examples/board-points-right.json --output calibration-right.json
```

The example references cover the left and right halves of the board. Change them to the intersections actually visible to your cameras. The UI tells you which board coordinate to click next. At least four non-collinear correspondences are required; five or more allow a consistency residual to be checked.

Both calibrations describe the same full board dimensions, even if a camera sees only half. Distribute reference points across each camera's visible board region. Do not extrapolate far outside that region without checking accuracy.

Calibration and session capture both request 1280×720. Actual supported camera resolution is recorded and checked; changing it requires recalibration. You can override --width and --height when calibrating and match those values in the session JSON.

## 6. Run one or two cameras

Edit examples/session.json:

- Set the trained weights path; paths are relative to the JSON file.
- Set source indices and calibration files.
- For a one-camera experiment, remove the second camera entry.
- Set the Foundry scene ID and bridge URL.
- Set bridge to null for a vision-only experiment.
- Set device to 0 for a suitable GPU or cpu as appropriate.

If using Foundry, start the bridge and module first, and set TOKEN_TRACKER_KEY in the tracker shell.

```powershell
python -m token_tracker.session examples/session.json --log moves.jsonl
```

Controls: Space pauses; G toggles the grid; R clears confirmed positions to emit fresh stable positions again; Esc exits.

Each view supplies board coordinates for the same physical class. Conflicting views are withheld. One clear view is sufficient when the other is stale, absent or geometrically weak. The geometric sensitivity check estimates the effect of a two-pixel keypoint error; it is not a statistical bound on model error.

The capture threads keep only the latest frame, preventing an ever-growing input queue. Inference currently runs sequentially for the two views. If CPU inference is too slow, start with one view and a smaller image size, or use a GPU. Increasing max_age_ms permits slower operation but also increases stale-observation risk; it does not satisfy the latency target by itself.

## 7. Measure acceptance behavior

Use held-out move trials, including ordinary moves, hand occlusions, pieces sharing a square, removed pieces and confusing pairs. Ground truth requires piece_id, final column/row and settled_at on the same monotonic clock as the tracker log.

```powershell
python -m token_tracker.evaluate truth.jsonl moves.jsonl --output evaluation.json
```

The scorer reports correct, wrong and missed moves, extra updates and p50/p95 latency for correct emissions. It matches the first update after a piece settles, not a later corrected position. Emission latency does **not** include Foundry acknowledgement time, so it cannot establish the full end-to-end 500 ms target.

Suggested first acceptance run: at least 100 moves across the distinct pieces, with separately reported occlusion/overlap cases. Do not claim 95% based only on easy moves or detector mAP.

## Remaining work requiring real hardware/data

- Train and evaluate actual miniature weights.
- Check the labeler's interaction and calibration UI on the team's machines.
- Verify webcams, resolutions, USB bandwidth and inference throughput.
- Validate the module in a licensed Foundry v13 world and chosen game system.
- Measure true end-to-end latency and identity/grid accuracy.
- Improve identical-piece identity and long-occlusion recovery if needed.

The current class-per-piece model replaces reusable appearance-profile registration with a fixed trained inventory. That is a deliberate first-prototype limitation, not completion of every PRD requirement.
