import tempfile
from pathlib import Path
import unittest
import numpy as np
from token_tracker.calibration import Calibration

class CalibrationTests(unittest.TestCase):
    def test_perspective_and_partial_coverage(self):
        h=np.array([[0.02,0.002,-1],[0.001,0.04,-2],[0.0001,0.0002,1.]])
        points=np.array([[100,100],[500,110],[490,300],[90,290],[300,200]],dtype=float)
        targets=[]
        for x,y in points:
            p=h@np.array([x,y,1]); targets.append(p[:2]/p[2])
        board=Calibration.from_points(points,targets,12,8,(1280,720))
        p=h@np.array([200,150,1]); expected=p[:2]/p[2]
        np.testing.assert_allclose(board.project(200,150),expected,atol=1e-6)
        self.assertLess(board.residual_cells,1e-6)

    def test_save_load_and_pixel_uncertainty(self):
        board=Calibration.from_corners([[0,0],[1200,0],[1200,800],[0,800]],12,8,(1280,720))
        self.assertAlmostEqual(board.uncertainty(600,400),0.02,places=5)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"board.json";board.save(path);loaded=Calibration.load(path)
            self.assertEqual(loaded.image_size,(1280,720))
            np.testing.assert_allclose(loaded.project(300,200),(3,2),atol=1e-6)

    def test_reject_collinear_and_wrong_correspondence(self):
        with self.assertRaises(ValueError):
            Calibration.from_points([[0,0],[100,0],[200,0],[300,0]],[[0,0],[1,0],[2,0],[3,0]],12,8)
        with self.assertRaises(ValueError):
            Calibration.from_corners([[0,0],[100,100],[100,0],[0,100]],12,8)
        with self.assertRaises(ValueError):
            Calibration.from_points([[0,0],[1200,0],[1200,800],[0,800],[600,400]],[[0,0],[12,0],[12,8],[0,8],[1,1]],12,8)

    def test_edge_on_view_has_large_uncertainty(self):
        board=Calibration.from_corners([[0,0],[1200,0],[1200,8],[0,8]],12,8)
        self.assertGreater(board.uncertainty(600,4),0.35)
