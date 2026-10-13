import json
import tempfile
from pathlib import Path
import unittest
from token_tracker.dataset import pose_label,validate_label,split_dataset

class DatasetTests(unittest.TestCase):
    def test_pose_format_and_validation(self):
        label=pose_label(0,(10,20,30,40),(25,55),100,100)
        validate_label(label,1)
        self.assertEqual(len(label.split()),8)
        with self.assertRaises(ValueError):validate_label(label,0)
        with self.assertRaises(ValueError):pose_label(0,(-1,0,20,20),(10,10),100,100)

    def build(self,root,duplicate=False):
        for session_id in range(3):
            folder=root/str(session_id);(folder/"images").mkdir(parents=True);(folder/"labels").mkdir()
            (folder/"manifest.json").write_text(json.dumps({"class_names":["goblin"]}))
            for camera in range(2):
                name=f"camera{camera}.jpg"
                (folder/"images"/name).write_bytes(b"duplicate" if duplicate else f"session{session_id}camera{camera}".encode())
                (folder/"labels"/(Path(name).stem+".txt")).write_text(pose_label(0,(10,20,30,40),(25,55),100,100))
            (folder/"images"/"unlabeled.jpg").write_bytes(b"unlabeled")

    def test_session_split_and_missing_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"sessions";root.mkdir();self.build(root)
            output=Path(temp)/"dataset";report=split_dataset(root,output,["goblin"])
            self.assertEqual(report["images"],{"test":2,"val":2,"train":2})
            self.assertEqual(len(set(sum(report["session_splits"].values(),[]))),3)
            config=json.loads((output/"dataset.yaml").read_text());self.assertEqual(config["kpt_shape"],[1,3])
            with self.assertRaises(ValueError):split_dataset(root,output,["goblin"])

    def test_reject_duplicate_images_across_splits(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"sessions";root.mkdir();self.build(root,duplicate=True)
            with self.assertRaisesRegex(ValueError,"Duplicate image"):
                split_dataset(root,Path(temp)/"dataset",["goblin"])
