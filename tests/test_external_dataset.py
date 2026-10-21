import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from token_tracker.external_dataset import inspect_export, import_export, load_workspace, save_review, prepare, annotate


class ExternalDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "export"
        self.workspace = self.root / "review"
        self.output = self.root / "pose"
        self.source.mkdir()
        (self.source / "data.yaml").write_text("names: [Gornak, Lemi]\nnc: 2\ntrain: ../train/images\nval: ../valid/images\ntest: ../test/images\n", encoding="utf-8")
        for index, split in enumerate(("train", "valid", "test")):
            (self.source / split / "images").mkdir(parents=True)
            (self.source / split / "labels").mkdir()
            Image.new("RGB", (100, 100), (50+index*30, 100, 150)).save(self.source / split / "images" / "frame.png")
            (self.source / split / "labels" / "frame.txt").write_text("0 .25 .5 .3 .5\n1 .75 .5 .3 .5\n")

    def tearDown(self):
        self.temp.cleanup()

    def imported(self):
        import_export(self.source, self.workspace, "https://example.com/source", "CC BY 4.0")
        return load_workspace(self.workspace)[1]

    def review_all(self, manifest):
        for item in manifest["items"]:
            save_review(self.workspace, item, [(25, 70, 2), (75, 70, 1)])

    def test_audit_preserves_names_and_reports_actual_split_counts(self):
        report, records = inspect_export(self.source)
        self.assertEqual(report["names"], ["Gornak", "Lemi"])
        self.assertEqual(report["images"], {"train":1,"val":1,"test":1})
        self.assertEqual(len(records), 3)
        self.assertEqual(report["invalid_files"], [])
        self.assertIn("not been established", report["split_provenance"])

    def test_import_keeps_boxes_without_fabricating_pose_labels(self):
        manifest = self.imported()
        self.assertEqual(manifest["license"], "CC BY 4.0")
        self.assertEqual(list((self.workspace / "labels").iterdir()), [])
        boxes = json.loads((self.workspace / manifest["items"][0]["boxes"]).read_text())
        self.assertEqual(boxes[0], [0, .25, .5, .3, .5])
        self.assertEqual(manifest["names"], ["Gornak", "Lemi"])

    def test_review_prepare_retains_identity_boxes_and_visibility(self):
        manifest = self.imported()
        self.review_all(manifest)
        report = prepare(self.workspace, self.output)
        config = json.loads((self.output / "dataset.yaml").read_text())
        self.assertEqual(config["kpt_shape"], [1,3])
        self.assertEqual(config["names"], ["Gornak", "Lemi"])
        self.assertEqual(report["images"], {"train":1,"val":1,"test":1})
        label = next((self.output / "labels/train").glob("*.txt")).read_text().splitlines()
        self.assertEqual(len(label[0].split()), 8)
        self.assertEqual(label[1].split()[7], "1")
        self.assertAlmostEqual(float(label[0].split()[6]), .7)

    def test_unlocalizable_boxes_remain_with_visibility_zero(self):
        manifest = self.imported()
        item = manifest["items"][0]
        save_review(self.workspace, item, [(25,70,2), None])
        lines = (self.workspace / "labels" / (item["id"]+".txt")).read_text().splitlines()
        self.assertEqual(lines[1].split()[5:], ["0", "0", "0"])
        self.assertEqual(lines[1].split()[0], "1")

    def test_no_keypoint_coverage_cannot_produce_trainable_pose_dataset(self):
        manifest = self.imported()
        for item in manifest["items"]:
            save_review(self.workspace, item, [None, None])
        with self.assertRaisesRegex(ValueError, "localized training"):
            prepare(self.workspace, self.output)
        self.assertFalse(self.output.exists())

    def test_unreviewed_images_are_excluded_not_negative(self):
        manifest = self.imported()
        with self.assertRaisesRegex(ValueError, "training and validation"):
            prepare(self.workspace, self.output)
        for item in manifest["items"]:
            if item["split"] != "test":
                save_review(self.workspace, item, [(25,70,2),(75,70,2)])
        report = prepare(self.workspace, self.output)
        self.assertEqual(report["unreviewed_excluded"], 1)
        self.assertNotIn("test", json.loads((self.output / "dataset.yaml").read_text()))

    def test_missing_source_labels_are_not_imported(self):
        (self.source / "test/labels/frame.txt").unlink()
        report, records = inspect_export(self.source)
        self.assertEqual(report["missing_labels"], {"test":1})
        self.assertEqual(len(records), 2)

    def test_explicit_negative_requires_review_but_can_be_preserved(self):
        (self.source / "test/labels/frame.txt").write_text("")
        manifest = self.imported()
        for item in manifest["items"]:
            save_review(self.workspace, item, [] if item["split"] == "test" else [(25,70,2),(75,70,2)])
        prepare(self.workspace, self.output)
        self.assertEqual(next((self.output / "labels/test").glob("*.txt")).read_text(), "")

    def test_invalid_and_segmentation_labels_block_import(self):
        for line in ("0 .5 .5 2 .4", "5 .5 .5 .4 .4", "0 nan .5 .4 .4", "0 .1 .2 .3 .4 .5 .6"):
            with self.subTest(line=line):
                (self.source / "train/labels/frame.txt").write_text(line)
                report, _ = inspect_export(self.source)
                self.assertEqual(len(report["invalid_files"]), 1)
                with self.assertRaisesRegex(ValueError, "invalid"):
                    import_export(self.source, self.workspace)
                self.assertFalse(self.workspace.exists())

    def test_cross_split_duplicate_images_block_import(self):
        (self.source / "test/images/frame.png").write_bytes((self.source / "train/images/frame.png").read_bytes())
        with self.assertRaisesRegex(ValueError, "Cross-split"):
            import_export(self.source, self.workspace)

    def test_cross_split_roboflow_augmentation_families_block_import(self):
        for split, name in (("train","original.rf.aaa.png"),("valid","original.rf.bbb.png")):
            (self.source / split / "images/frame.png").rename(self.source / split / "images" / name)
            (self.source / split / "labels/frame.txt").rename(self.source / split / "labels" / (Path(name).stem+".txt"))
        report, _ = inspect_export(self.source)
        self.assertEqual(report["cross_split_source_groups"], ["original"])
        with self.assertRaisesRegex(ValueError, "Cross-split"):
            import_export(self.source, self.workspace)

    def test_repeated_class_identity_is_reported(self):
        (self.source / "train/labels/frame.txt").write_text("0 .25 .5 .3 .5\n0 .75 .5 .3 .5")
        report, _ = inspect_export(self.source)
        self.assertEqual(report["images_with_repeated_class"]["train"], 1)

    def test_reused_filenames_for_different_classes_are_not_source_leakage(self):
        for split, suffix, class_id in (("train", "aaa", 0), ("valid", "bbb", 1)):
            name = "0_jpg.rf." + suffix
            (self.source / split / "images/frame.png").rename(self.source / split / "images" / (name+".png"))
            (self.source / split / "labels/frame.txt").unlink()
            (self.source / split / "labels" / (name+".txt")).write_text(str(class_id)+" .5 .5 1 1")
        report, _ = inspect_export(self.source)
        self.assertEqual(report["cross_split_source_groups"], [])
        self.assertEqual(report["full_frame_box_images"], 2)
        self.imported()

    def test_tampered_images_and_box_edits_fail_prepare(self):
        manifest = self.imported()
        self.review_all(manifest)
        item = manifest["items"][0]
        label = self.workspace / "labels" / (item["id"]+".txt")
        old = label.read_text()
        label.write_text(old.replace("0.25000000", "0.26000000", 1))
        with self.assertRaisesRegex(ValueError, "differs from source"):
            prepare(self.workspace, self.output)
        label.write_text(old)
        (self.workspace / item["image"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Image changed"):
            prepare(self.workspace, self.output)

    def test_manifest_paths_cannot_escape_workspace(self):
        manifest = self.imported()
        manifest["items"][0]["image"] = "../outside.png"
        (self.workspace / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "inside"):
            load_workspace(self.workspace)

    def test_safe_yaml_rejects_python_object_tags(self):
        import yaml
        (self.source / "data.yaml").write_text("!!python/object/apply:os.system ['echo unsafe']")
        with self.assertRaises(yaml.YAMLError):
            inspect_export(self.source)

    def test_labeler_maps_scaled_clicks_and_keeps_skipped_box(self):
        for index, split in enumerate(("train", "valid", "test")):
            Image.new("RGB", (2400,1440), (50+index*30,100,150)).save(self.source / split / "images/frame.png")
        manifest = self.imported()
        callbacks, keys = {}, iter([13, ord('x'), ord('s'), 27])
        def wait(ms):
            key = next(keys)
            if key == 13:
                callbacks['click'](1, 300, 504, None, None)
            return key
        fake = types.SimpleNamespace(EVENT_LBUTTONDOWN=1, FONT_HERSHEY_SIMPLEX=0,
            namedWindow=lambda *a:None, setMouseCallback=lambda w, fn:callbacks.update(click=fn),
            imread=lambda p:np.zeros((1440,2400,3),dtype=np.uint8), resize=lambda a,b:np.zeros((b[1],b[0],3),dtype=np.uint8),
            rectangle=lambda *a:None, putText=lambda *a:None, circle=lambda *a:None,
            imshow=lambda *a:None, waitKey=wait, destroyAllWindows=lambda:None)
        with patch.dict('sys.modules', {'cv2':fake}):
            annotate(self.workspace)
        item = manifest["items"][0]
        lines = (self.workspace / "labels" / (item["id"]+".txt")).read_text().splitlines()
        self.assertEqual(float(lines[0].split()[5]), .25)
        self.assertEqual(lines[1].split()[7], "0")


if __name__ == "__main__":
    unittest.main()
