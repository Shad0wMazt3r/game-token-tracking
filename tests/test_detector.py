import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from token_tracker.detector import YoloBaseDetector

class Tensor:
    def __init__(self,data): self.data=np.asarray(data)
    def cpu(self): return self
    def tolist(self): return self.data.tolist()
    def __getitem__(self,index):
        value=self.data[index]
        return Tensor(value) if isinstance(value,np.ndarray) else value

class DetectorTests(unittest.TestCase):
    def fake(self,shape=(1,3),classes=(0,),confidence=0.9):
        count=len(classes)
        result=SimpleNamespace(boxes=SimpleNamespace(cls=Tensor(classes)),names={0:"goblin"},
          keypoints=SimpleNamespace(data=np.zeros((count,*shape)),conf=Tensor([[confidence]]*count),xy=Tensor([[[25,40]]]*count)))
        model=SimpleNamespace(task="pose",model=SimpleNamespace(model=[SimpleNamespace(kpt_shape=shape)]),predict=lambda *a,**k:[result])
        return {"ultralytics":SimpleNamespace(YOLO=lambda *a:model)}

    def test_reject_human_pose_weights(self):
        with patch.dict(sys.modules,self.fake(shape=(17,3))):
            with self.assertRaises(ValueError):YoloBaseDetector("unused")

    def test_extract_base_and_reject_duplicate_identity(self):
        with patch.dict(sys.modules,self.fake()):
            points=YoloBaseDetector("unused").detect(None)
            self.assertEqual((points[0].piece_id,points[0].x,points[0].y),("goblin",25,40))
        with patch.dict(sys.modules,self.fake(classes=(0,0))):
            self.assertEqual(YoloBaseDetector("unused").detect(None),[])

    def test_hidden_or_uncertain_keypoint_is_withheld(self):
        with patch.dict(sys.modules,self.fake(confidence=0.1)):
            self.assertEqual(YoloBaseDetector("unused").detect(None),[])
