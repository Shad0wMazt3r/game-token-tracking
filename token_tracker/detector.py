"""Pose adapter: keypoint zero is the base center on the board plane."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Observation:
    piece_id: str
    x: float
    y: float
    confidence: float

class YoloBaseDetector:
    def __init__(self, weights, confidence=0.5, keypoint_confidence=0.5):
        from ultralytics import YOLO
        self.model = YOLO(weights)
        if self.model.task != "pose":
            raise ValueError("Use custom pose weights with base-center keypoint zero")
        self.confidence = confidence
        self.keypoint_confidence = keypoint_confidence

    def detect(self, frame):
        result = self.model.predict(frame, conf=self.confidence, verbose=False)[0]
        observations = []
        if result.keypoints is None:
            return observations
        # Fixed-set prototype: one unique visual class per physical piece.
        # Duplicate classes are ambiguous and deliberately withheld.
        classes = result.boxes.cls.cpu().tolist()
        for i, class_id in enumerate(classes):
            if classes.count(class_id) != 1:
                continue
            confidence = result.keypoints.conf
            if confidence is None or float(confidence[i,0]) < self.keypoint_confidence:
                continue
            x,y = result.keypoints.xy[i,0].cpu().tolist()
            observations.append(Observation(str(result.names[int(class_id)]), x, y, float(confidence[i,0])))
        return observations
