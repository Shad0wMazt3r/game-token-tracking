# DnD Minis dataset pilot

[Documentation home](../README.md) · [Capture/training walkthrough](prototype-walkthrough.md) · [Dashboard](dashboard.md)

This workflow adapts a **YOLO object-detection export** to our one-base-keypoint pose model. Existing boxes and class names are retained. An operator reviews each object and adds its board-plane base center; the importer never invents keypoints from bounding-box centers or bottom edges.

## Source and present evidence

Candidate: [DnD Minis by DnD on Roboflow Universe](https://universe.roboflow.com/dnd-uz8oh/dnd-minis-iaduc). The project page lists six classes, about 1,100 project images and CC BY 4.0. Individual dataset versions have different image counts. This is a candidate, not a verified match to unmounted webcam geometry.

The integration is tested with generated image files and representative YOLO export fixtures. Version 5 has now been audited locally: 1,032 labeled images (749 train / 191 validation / 92 test), five classes, one labeled mini per image, and 1,022 full-frame boxes. No invalid boxes, missing labels or cross-split byte-identical images were found. Matching numeric filenames occur across different classes and are not treated as shared-source evidence. A class-aware filename check found no cross-split families. Similar-looking adjacent frames remain a concern; neither check establishes session independence.

Visual samples are tightly cropped individual minis, with colored bases on a simple background. This is useful as a recognition/appearance pilot for those five pieces, but weak evidence for detecting small minis in full tabletop scenes. No base keypoints have been added and no model has been trained on the archive. Download access may require a Roboflow account. No hosted model API or API key is needed by the local importer.

## 1. Download a detection export

Choose a dataset version and download **YOLO bounding-box detection format**, for example YOLOv8 detection. Extract the ZIP yourself into `datasets/dnd-export`. Do not choose segmentation, classification, or a hosted-model inference snippet. Keep the supplied attribution/license information.

Supported layouts:

```text
data.yaml
train/images/ and train/labels/
valid/images/ and valid/labels/
test/images/ and test/labels/
```

The `images/train`, `labels/train` style is also supported; `val` and `validation` are accepted aliases. The importer discovers those standard folders rather than following arbitrary paths from the YAML. JPG, JPEG, PNG, WEBP and BMP images are accepted. Detection label rows must contain exactly `class cx cy width height` with normalized coordinates.

Update dependencies with `python -m pip install -e ".[yolo]"`.

## 2. Audit before labeling

```powershell
python -m token_tracker.external_dataset audit datasets/dnd-export --output dnd-audit.json
```

Inspect actual image/split counts, class counts, missing labels, malformed boxes, unreadable images, repeated classes per image, byte-identical images across splits, and recognized Roboflow augmentation families crossing splits.

Missing labels are excluded, not treated as empty negatives. A present empty label is an explicit source negative, which still requires review before preparation. EXIF-rotated images are rejected because image orientation and box coordinates must agree.

Cross-split duplicates and recognized augmentation families block import. Fix the source splits before retrying. These checks cannot establish independence between recording sessions or catch all near-duplicates. Provider splits remain explicitly unverified.

## 3. Import boxes into a separate review workspace

```powershell
python -m token_tracker.external_dataset import datasets/dnd-export datasets/dnd-review --source-url https://universe.roboflow.com/dnd-uz8oh/dnd-minis-iaduc --license "CC BY 4.0"
```

Choose a new output directory outside the source export. This copies only explicitly labeled source images, stores their boxes separately, and records original paths, hashes, source URL, license statement and split assignment. It creates **no pose labels** yet and does not alter the downloaded export. Specify the license from the version you actually download; the command records your statement, not an independent rights determination.

## 4. Click base centers instead of redrawing boxes

For a small pilot, review training and validation images separately:

```powershell
python -m token_tracker.external_dataset annotate datasets/dnd-review --split train --limit 60
python -m token_tracker.external_dataset annotate datasets/dnd-review --split val --limit 20
python -m token_tracker.external_dataset annotate datasets/dnd-review --split test --limit 20
```

The counts are initial review limits, not an accuracy guarantee. Include examples of every class in training and representative poses in validation. Rerun to resume; already saved images are skipped. Use `--relabel` to replace an existing review; it starts that frame from the source boxes again.

- The current object's existing box is highlighted. Click its base center **on the board plane** and press Enter to accept it.
- V toggles visible (2) / occluded but reliably localizable (1).
- X marks the current object's base unlocalizable (visibility 0). Its detection box stays in the pose label, with no supervised keypoint target.
- U undoes the last accepted object.
- S saves only after every source object is resolved. For a negative frame with zero source boxes, S saves an empty pose label.
- N skips the whole frame without creating a label. Esc exits.

Large images are resized for display; clicks are mapped back to original pixel coordinates. Source classes and boxes remain unchanged. Review poorly placed source boxes in the original export before import; this tool does not edit them. If the base center cannot be inferred reliably, use X or skip the frame rather than guessing.

## 5. Prepare a trainable pose dataset

```powershell
python -m token_tracker.external_dataset prepare datasets/dnd-review datasets/dnd-pose
```

This excludes unreviewed frames, preserves the provider split assignments, verifies image hashes and unchanged class/box annotations, checks duplicates again, and writes `dataset.yaml` with `kpt_shape: [1,3]` plus an import report. Every class needs localized training base examples; validation must contain localized bases. These are minimum format checks, not adequate sample-size requirements.

An independently held-out test split is strongly preferable. If no test images were reviewed, no `test` entry is created; validation results must not be presented as independent test results. Keep source attribution with downstream artifacts.

## 6. Train on Nova

Upload the prepared dataset and repository to Nova and use a Python environment with the project dependencies and a CUDA-compatible PyTorch installation. Absolute paths in `dataset.yaml` must point to its location **on Nova**; update `path` after transfer. Do not run training on a login node.

After obtaining a GPU allocation, a one-epoch smoke test is:

```bash
python -m token_tracker.dataset train /absolute/path/dnd-pose/dataset.yaml --device 0 --epochs 1 --imgsz 960
```

For a batch job, activate your environment and submit with your real account/partition:

```bash
sbatch -A YOUR_ACCOUNT -p YOUR_PARTITION scripts/train-nova.sbatch /absolute/path/dnd-pose/dataset.yaml
```

The script requests one GPU, four CPU cores, 16 GB RAM and a two-hour limit as initial resource settings; this is not a training-time estimate. It checks that CUDA and the one-keypoint dataset are available. Override epochs with `EPOCHS=1 sbatch ...` for a smoke run. Adjust resources based on observed use and account limits.

The pretrained weights must be accessible to the job. Stage them in advance if compute nodes cannot download files. Training writes its standard Ultralytics run directory; retain the actual `best.pt` path, source/version information and environment versions.

```bash
yolo pose val model=runs/pose/train/weights/best.pt data=/absolute/path/dnd-pose/dataset.yaml split=test
```

Only request `split=test` if a reviewed test split exists. Use the actual run directory, which may be `train2` etc. Download trained pose weights for the dashboard; raw box-only detection weights remain incompatible and are still rejected by the runtime.

## What a positive pilot would establish

It can establish that the data can be imported, base points can be learned on those images, and the trained model produces our expected pose output. It does not establish identity recognition for new minis, grid-square accuracy without board calibration, or performance from the team's future low webcam placements.

The current runtime treats classes as unique physical identities. If a source class appears multiple times in a frame, it is ambiguous under that design. Audit warnings expose this; importing does not silently assign new identities. Test with the source classes first, then fine-tune and evaluate on actual equipment and pieces.

Nova references: [GPU allocations](https://research.it.iastate.edu/gpus), [cluster access and Slurm](https://research.it.iastate.edu/nova).
