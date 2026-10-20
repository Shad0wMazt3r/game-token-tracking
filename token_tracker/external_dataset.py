"""Audit YOLO detection exports and review their base keypoints without relabeling boxes."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import shutil
from .dataset import pose_label, validate_label

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def inside(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Dataset paths must stay inside the selected directory")
    return path


def read_names(root):
    import yaml
    configs = [p for p in (root / "data.yaml", root / "dataset.yaml") if p.is_file()]
    if len(configs) != 1:
        raise ValueError("Export must contain exactly one data.yaml or dataset.yaml")
    config = yaml.safe_load(configs[0].read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Dataset YAML must be a mapping")
    names = config.get("names")
    if isinstance(names, dict):
        if any(type(k) is not int for k in names) or sorted(names) != list(range(len(names))):
            raise ValueError("Class IDs must be contiguous integers starting at zero")
        names = [names[i] for i in range(len(names))]
    if (not isinstance(names, list) or not names or
        any(not isinstance(n, str) or not n.strip() for n in names) or len(set(names)) != len(names)):
        raise ValueError("Dataset needs unique, nonempty class names")
    if "nc" in config and (type(config["nc"]) is not int or config["nc"] != len(names)):
        raise ValueError("nc does not match the class list")
    if config.get("kpt_shape"):
        raise ValueError("This importer expects detection boxes, not an existing pose dataset")
    return names


def parse_box(line, class_count):
    fields = line.split()
    if len(fields) != 5:
        raise ValueError("Expected YOLO detection rows: class cx cy width height; pose/segmentation exports are different")
    try:
        class_id = int(fields[0])
        values = list(map(float, fields[1:]))
    except ValueError as error:
        raise ValueError("Invalid detection row") from error
    if not 0 <= class_id < class_count or not all(math.isfinite(v) and 0 <= v <= 1 for v in values):
        raise ValueError("Invalid detection class or normalized coordinates")
    cx, cy, width, height = values
    if width <= 0 or height <= 0 or cx-width/2 < -1e-7 or cy-height/2 < -1e-7 or cx+width/2 > 1+1e-7 or cy+height/2 > 1+1e-7:
        raise ValueError("Detection box does not fit inside the image")
    return [class_id, *values]


def inspect_export(root):
    """Read standard split folders; never execute or follow YAML-provided paths."""
    from PIL import Image
    root = Path(root).resolve()
    names = read_names(root)
    records, issues, hashes, groups = [], [], defaultdict(set), defaultdict(set)
    missing, counts, objects, repeated = Counter(), Counter(), Counter(), Counter()
    for split, aliases in (("train", ["train"]), ("val", ["valid", "val", "validation"]), ("test", ["test"])):
        layouts = [(root / alias / "images", root / alias / "labels") for alias in aliases]
        layouts += [(root / "images" / alias, root / "labels" / alias) for alias in aliases]
        available = [(a, b) for a, b in layouts if a.is_dir()]
        if len(available) > 1:
            raise ValueError("Multiple layouts found for split " + split)
        if not available:
            continue
        image_dir, label_dir = available[0]
        stems = set()
        for image in sorted(image_dir.iterdir()):
            if not image.is_file() or image.suffix.lower() not in IMAGE_TYPES:
                continue
            image = inside(root, image.relative_to(root))
            label = inside(root, (label_dir / (image.stem + ".txt")).relative_to(root))
            if image.stem in stems:
                issues.append(str(image.relative_to(root)) + ": image stem collision")
                continue
            stems.add(image.stem)
            try:
                with Image.open(image) as opened:
                    size = opened.size
                    if getattr(opened, "n_frames", 1) != 1:
                        raise ValueError("Animated images are unsupported")
                    if opened.getexif().get(274, 1) != 1:
                        raise ValueError("Normalize EXIF orientation and update annotations before importing")
                # EXIF inspection may load PNG metadata; verify a fresh handle.
                with Image.open(image) as verified:
                    verified.verify()
                digest = hashlib.sha256(image.read_bytes()).hexdigest()
                hashes[digest].add(split)
                # Roboflow augmentation exports commonly retain the original prefix.
                if ".rf." in image.name:
                    groups[image.name.split(".rf.")[0]].add(split)
                counts[split] += 1
                if not label.is_file():
                    missing[split] += 1
                    continue  # Never turn missing labels into negative examples.
                boxes = [parse_box(line, len(names)) for line in label.read_text(encoding="utf-8").splitlines() if line.strip()]
                classes = Counter(box[0] for box in boxes)
                repeated[split] += int(any(n > 1 for n in classes.values()))
                for box in boxes:
                    objects[names[box[0]]] += 1
                records.append(dict(split=split, image=str(image.relative_to(root)), label=str(label.relative_to(root)),
                                    sha256=digest, size=list(size), boxes=boxes))
            except (ValueError, OSError, Image.DecompressionBombError) as error:
                issues.append(str(image.relative_to(root)) + ": " + str(error))
    if not counts:
        raise ValueError("No supported images found. Use train/images, valid/images, test/images or images/train layouts")
    byte_leaks = [digest for digest, splits in hashes.items() if len(splits) > 1]
    source_leaks = [name for name, splits in groups.items() if len(splits) > 1]
    report = dict(names=names, images=dict(counts), missing_labels=dict(missing), labeled_images=len(records),
                  objects=dict(objects), images_with_repeated_class=dict(repeated), invalid_files=issues,
                  cross_split_duplicate_hashes=byte_leaks, cross_split_source_groups=source_leaks,
                  split_provenance="Provider splits; independence by recording session has not been established",
                  warnings=["Bounding boxes do not supply board-plane base centers.",
                            "Classes are source identities/types, not automatically your future physical pieces.",
                            "Repeated classes in one frame are withheld by the current fixed-identity runtime.",
                            "Different bytes or filenames do not rule out near-duplicate frames or session leakage."])
    return report, records


def import_export(source, destination, source_url="", license_name="unspecified"):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError("Choose a new workspace outside the source export")
    report, records = inspect_export(source)
    if not records:
        raise ValueError("No explicitly labeled images available to import")
    if report["invalid_files"]:
        raise ValueError("Fix invalid images/labels before import; run audit for details")
    if report["cross_split_duplicate_hashes"] or report["cross_split_source_groups"]:
        raise ValueError("Cross-split duplicates/source groups detected; fix the source splits before importing")
    destination.mkdir(parents=True)
    for folder in ("images", "boxes", "labels"):
        (destination / folder).mkdir()
    items = []
    for index, record in enumerate(records):
        image = inside(source, record["image"])
        item_id = f"{record['split']}_{index:06d}_{record['sha256'][:12]}"
        relative = "images/" + item_id + image.suffix.lower()
        shutil.copy2(image, destination / relative)
        write_json(destination / "boxes" / (item_id + ".json"), record["boxes"])
        items.append(dict(id=item_id, image=relative, boxes="boxes/"+item_id+".json", split=record["split"],
                          original_image=record["image"], sha256=record["sha256"], size=record["size"]))
    manifest = dict(format="external-base-review-v1", names=report["names"], source_url=source_url,
                    license=license_name, split_provenance=report["split_provenance"], items=items)
    write_json(destination / "manifest.json", manifest)
    write_json(destination / "audit.json", report)
    return report


def load_workspace(root):
    root = Path(root).resolve()
    manifest = read_json(root / "manifest.json")
    if manifest.get("format") != "external-base-review-v1":
        raise ValueError("Use an imported external review workspace")
    items = manifest.get("items", [])
    if len({item["id"] for item in items}) != len(items):
        raise ValueError("Duplicate workspace item IDs")
    for item in items:
        if not item["id"] or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in item["id"]):
            raise ValueError("Invalid workspace item ID")
        inside(root, item["image"])
        inside(root, item["boxes"])
        if item["split"] not in ("train", "val", "test"):
            raise ValueError("Invalid workspace split")
    return root, manifest


def save_review(root, item, points):
    """None means unlocalizable, never an invented bounding-box-center keypoint."""
    root, manifest = load_workspace(root)
    canonical = next((row for row in manifest["items"] if row["id"] == item["id"]), None)
    if canonical != item:
        raise ValueError("Item does not match this workspace")
    boxes = read_json(inside(root, item["boxes"]))
    if len(points) != len(boxes):
        raise ValueError("Resolve every box before saving")
    width, height = item["size"]
    labels = []
    for box, point in zip(boxes, points):
        class_id, cx, cy, w, h = parse_box(" ".join(map(str, box)), len(manifest["names"]))
        if point is None:
            line = " ".join(map(str, [class_id, cx, cy, w, h, 0, 0, 0]))
        else:
            if len(point) != 3 or point[2] not in (1, 2):
                raise ValueError("Point needs pixel x, pixel y and visibility 1 or 2")
            # Clamp sub-pixel roundoff already accepted by normalized-box validation.
            left, top = max(0, (cx-w/2)*width), max(0, (cy-h/2)*height)
            right, bottom = min(width, (cx+w/2)*width), min(height, (cy+h/2)*height)
            line = pose_label(class_id, (left, top, right-left, bottom-top), point[:2], width, height, point[2])
        validate_label(line, len(manifest["names"]))
        labels.append(line)
    path = root / "labels" / (item["id"] + ".txt")
    temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(labels) + ("\n" if labels else ""), encoding="utf-8")
    temporary.replace(path)
    return len(labels)


def annotate(root, relabel=False, split=None, limit=None):
    import cv2
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("Review limit must be a positive integer")
    root, manifest = load_workspace(root)
    window = "Base review | click, Enter accept, V visibility, X unlocalizable, U undo, S save, N skip, Esc quit"
    cv2.namedWindow(window)
    try:
        presented = 0
        for item in manifest["items"]:
            if split is not None and item["split"] != split:
                continue
            output = root / "labels" / (item["id"] + ".txt")
            if output.exists() and not relabel:
                continue
            if limit is not None and presented >= limit:
                break
            presented += 1
            image = cv2.imread(str(inside(root, item["image"])))
            if image is None or (image.shape[1], image.shape[0]) != tuple(item["size"]):
                raise ValueError("Image dimensions changed after import")
            boxes = read_json(inside(root, item["boxes"]))
            width, height = item["size"]
            scale = min(1.0, 1200/width, 720/height)
            # Use actual integer resize dimensions for correct click inversion.
            display_width, display_height = max(1, round(width*scale)), max(1, round(height*scale))
            sx, sy = display_width/width, display_height/height
            points, pending, visibility = [], None, 2
            def click(event, x, y, flags, param):
                nonlocal pending
                if event == cv2.EVENT_LBUTTONDOWN and len(points) < len(boxes):
                    pending = (x/sx, y/sy)
            cv2.setMouseCallback(window, click)
            while True:
                view = cv2.resize(image, (display_width, display_height))
                for index, (class_id, cx, cy, w, h) in enumerate(boxes):
                    color = (60, 230, 180) if index == len(points) else (100, 110, 100)
                    a = (round((cx-w/2)*width*sx), round((cy-h/2)*height*sy))
                    b = (round((cx+w/2)*width*sx), round((cy+h/2)*height*sy))
                    cv2.rectangle(view, a, b, color, 2)
                    cv2.putText(view, str(index+1)+": "+manifest["names"][int(class_id)], a, cv2.FONT_HERSHEY_SIMPLEX, .45, color, 1)
                for point in points:
                    if point is not None:
                        cv2.circle(view, (round(point[0]*sx), round(point[1]*sy)), 4, (60, 230, 180), -1)
                if pending:
                    cv2.circle(view, (round(pending[0]*sx), round(pending[1]*sy)), 5, (40, 180, 255), -1)
                text = f"{item['split']} | {len(points)}/{len(boxes)} resolved | visibility {visibility} | S saves when complete"
                cv2.putText(view, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1)
                cv2.imshow(window, view)
                key = cv2.waitKey(20) & 255
                if key == 27:
                    return
                if key == ord("n"):
                    break
                if key == ord("v"):
                    visibility = 1 if visibility == 2 else 2
                if key == ord("u") and points:
                    points.pop(); pending = None
                if key == ord("x") and len(points) < len(boxes):
                    points.append(None); pending = None
                if key == 13 and pending is not None and len(points) < len(boxes):
                    points.append((*pending, visibility)); pending = None
                if key == ord("s"):
                    if len(points) != len(boxes):
                        print("Accept or mark unlocalizable every box before saving; N skips the whole frame")
                        continue
                    save_review(root, item, points)
                    break
    finally:
        cv2.destroyAllWindows()


def prepare(root, destination):
    root, manifest = load_workspace(root)
    destination = Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(root):
        raise ValueError("Choose a new dataset directory outside the review workspace")
    plans, hashes, source_groups = [], defaultdict(set), defaultdict(set)
    images, localized, unlocalized = Counter(), defaultdict(Counter), defaultdict(Counter)
    skipped = 0
    for item in manifest["items"]:
        label = root / "labels" / (item["id"] + ".txt")
        if not label.exists():
            skipped += 1
            continue
        lines = [line for line in label.read_text(encoding="utf-8").splitlines() if line.strip()]
        boxes = [parse_box(" ".join(map(str, row)), len(manifest["names"]))
                 for row in read_json(inside(root, item["boxes"]))]
        if len(lines) != len(boxes):
            raise ValueError("Reviewed labels must retain every source box, including unlocalizable objects")
        for line, box in zip(lines, boxes):
            validate_label(line, len(manifest["names"]))
            fields = list(map(float, line.split()))
            if any(abs(a-b) > 1e-6 for a, b in zip(fields[:5], box)):
                raise ValueError("Reviewed class/box differs from source annotation")
            counts = localized if fields[7] > 0 else unlocalized
            counts[item["split"]][int(fields[0])] += 1
        image = inside(root, item["image"])
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise ValueError("Image changed after import")
        hashes[digest].add(item["split"])
        original = Path(item["original_image"]).name
        if ".rf." in original:
            source_groups[original.split(".rf.")[0]].add(item["split"])
        plans.append((item, image, label))
        images[item["split"]] += 1
    if any(len(splits) > 1 for splits in list(hashes.values()) + list(source_groups.values())):
        raise ValueError("Reviewed subset contains cross-split duplicates or augmentation families")
    if not images["train"] or not images["val"]:
        raise ValueError("Review at least one training and validation image")
    missing_classes = [name for index, name in enumerate(manifest["names"]) if localized["train"][index] == 0]
    if missing_classes:
        raise ValueError("Every class needs at least one localized training base keypoint. Missing: " + ", ".join(missing_classes))
    if not sum(localized["val"].values()):
        raise ValueError("Validation needs localized base keypoints")
    for item, image, label in plans:
        image_dir, label_dir = destination / "images" / item["split"], destination / "labels" / item["split"]
        image_dir.mkdir(parents=True, exist_ok=True); label_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image, image_dir / image.name)
        shutil.copy2(label, label_dir / (image.stem + ".txt"))
    config = dict(path=destination.as_posix(), train="images/train", val="images/val",
                  names=manifest["names"], kpt_shape=[1, 3], flip_idx=[0])
    if images["test"]:
        config["test"] = "images/test"
    write_json(destination / "dataset.yaml", config)
    report = dict(images=dict(images), unreviewed_excluded=skipped, localized=dict(localized),
                  unlocalizable=dict(unlocalized), source_url=manifest["source_url"], license=manifest["license"],
                  split_provenance=manifest["split_provenance"],
                  note="Pilot on provider splits; not evidence of generalization to new pieces or independent webcam sessions")
    write_json(destination / "import-report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("audit"); p.add_argument("source"); p.add_argument("--output")
    p = sub.add_parser("import"); p.add_argument("source"); p.add_argument("destination")
    p.add_argument("--source-url", default=""); p.add_argument("--license", default="unspecified")
    p = sub.add_parser("annotate"); p.add_argument("workspace"); p.add_argument("--relabel", action="store_true")
    p.add_argument("--split", choices=["train", "val", "test"]); p.add_argument("--limit", type=int)
    p = sub.add_parser("prepare"); p.add_argument("workspace"); p.add_argument("destination")
    args = parser.parse_args()
    if args.command == "audit":
        report, _ = inspect_export(args.source)
        if args.output:
            write_json(args.output, report)
    elif args.command == "import":
        report = import_export(args.source, args.destination, args.source_url, args.license)
    elif args.command == "annotate":
        annotate(args.workspace, args.relabel, args.split, args.limit)
        return
    else:
        report = prepare(args.workspace, args.destination)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
