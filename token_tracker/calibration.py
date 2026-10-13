"""Planar calibration. Input points must lie on the board surface."""
from dataclasses import dataclass
import json
import cv2
import numpy as np

@dataclass
class Calibration:
    columns: int
    rows: int
    matrix: np.ndarray

    @classmethod
    def from_corners(cls, corners, columns, rows):
        if columns <= 0 or rows <= 0:
            raise ValueError("Grid dimensions must be positive")
        source = np.asarray(corners, dtype=np.float32)
        if source.shape != (4, 2) or not np.isfinite(source).all():
            raise ValueError("Four finite corners required: TL, TR, BR, BL")
        contour = source.reshape(-1, 1, 2)
        if not cv2.isContourConvex(contour) or abs(cv2.contourArea(contour)) < 100:
            raise ValueError("Corners must form a nondegenerate convex board")
        target = np.float32([[0,0],[columns,0],[columns,rows],[0,rows]])
        return cls(columns, rows, cv2.getPerspectiveTransform(source, target))

    def project(self, x, y):
        p = self.matrix @ np.array([x, y, 1.0])
        if abs(p[2]) < 1e-10:
            raise ValueError("Point cannot be projected")
        return float(p[0]/p[2]), float(p[1]/p[2])

    def save(self, filename):
        with open(filename, "w") as stream:
            json.dump(dict(columns=self.columns, rows=self.rows, matrix=self.matrix.tolist()), stream)

    @classmethod
    def load(cls, filename):
        with open(filename) as stream:
            data = json.load(stream)
        matrix = np.asarray(data["matrix"], dtype=float)
        if matrix.shape != (3,3) or not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) < 1e-12:
            raise ValueError("Invalid calibration matrix")
        if data["columns"] < 1 or data["rows"] < 1:
            raise ValueError("Invalid grid dimensions")
        return cls(data["columns"], data["rows"], matrix)
