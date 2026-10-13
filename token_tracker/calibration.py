"""Camera-to-board homographies, including partial camera coverage."""
from dataclasses import dataclass
import json
import math
import cv2
import numpy as np

@dataclass
class Calibration:
    columns: int
    rows: int
    matrix: np.ndarray
    image_size: tuple | None = None
    residual_cells: float = 0.0

    @classmethod
    def from_points(cls,image_points,board_points,columns,rows,image_size=None):
        if type(columns) is not int or type(rows) is not int or columns < 1 or rows < 1:
            raise ValueError("Grid dimensions must be positive integers")
        source=np.asarray(image_points,dtype=np.float64)
        target=np.asarray(board_points,dtype=np.float64)
        if source.ndim != 2 or source.shape[1] != 2 or len(source)<4 or target.shape != source.shape or not np.isfinite(source).all() or not np.isfinite(target).all():
            raise ValueError("At least four finite corresponding 2D points required")
        if (np.linalg.matrix_rank(source-source.mean(axis=0))<2 or
            np.linalg.matrix_rank(target-target.mean(axis=0))<2 or
            cv2.contourArea(cv2.convexHull(source.astype(np.float32)))<100):
            raise ValueError("Reference points must span a visible board region")
        matrix,_=cv2.findHomography(source,target,method=0)
        if matrix is None or not np.isfinite(matrix).all() or np.linalg.matrix_rank(matrix)<3:
            raise ValueError("Degenerate calibration")
        board=cls(columns,rows,matrix,tuple(image_size) if image_size else None)
        errors=[math.hypot(*(np.array(board.project(*p))-q)) for p,q in zip(source,target)]
        board.residual_cells=float(np.sqrt(np.mean(np.square(errors))))
        if board.residual_cells>0.15:
            raise ValueError("Reference points disagree by more than 0.15 cells RMS")
        return board

    @classmethod
    def from_corners(cls,corners,columns,rows,image_size=None):
        source=np.asarray(corners,dtype=np.float32)
        if source.shape != (4,2) or not np.isfinite(source).all() or not cv2.isContourConvex(source.reshape(-1,1,2)):
            raise ValueError("Corners must be ordered TL, TR, BR, BL and form a convex board")
        return cls.from_points(source,[[0,0],[columns,0],[columns,rows],[0,rows]],columns,rows,image_size)

    def project(self,x,y):
        p=self.matrix@np.array([x,y,1.0])
        if not np.isfinite(p).all() or abs(p[2])<1e-10:
            raise ValueError("Point cannot be projected")
        return float(p[0]/p[2]),float(p[1]/p[2])

    def uncertainty(self,x,y,pixel_error=2):
        center=self.project(x,y)
        try:
            return max(math.dist(center,self.project(x+dx,y+dy)) for dx,dy in ((pixel_error,0),(-pixel_error,0),(0,pixel_error),(0,-pixel_error)))
        except ValueError:
            return float("inf")

    def save(self,filename):
        with open(filename,"w") as stream:
            json.dump(dict(columns=self.columns,rows=self.rows,matrix=self.matrix.tolist(),image_size=self.image_size,residual_cells=self.residual_cells),stream,indent=2)

    @classmethod
    def load(cls,filename):
        with open(filename) as stream: data=json.load(stream)
        matrix=np.asarray(data["matrix"],dtype=float)
        if matrix.shape != (3,3) or not np.isfinite(matrix).all() or np.linalg.matrix_rank(matrix)<3:
            raise ValueError("Invalid calibration matrix")
        if type(data["columns"]) is not int or type(data["rows"]) is not int or data["columns"]<1 or data["rows"]<1:
            raise ValueError("Invalid grid dimensions")
        size=data.get("image_size")
        if size is not None and (len(size)!=2 or any(type(v) is not int or v<1 for v in size)):
            raise ValueError("Invalid calibration image size")
        return cls(data["columns"],data["rows"],matrix,tuple(size) if size else None,data.get("residual_cells",0))
