import unittest
from token_tracker.state import Stabilizer

class StateTests(unittest.TestCase):
    def test_stability_and_no_duplicate_updates(self):
        s=Stabilizer(10,10)
        self.assertIsNone(s.observe("a",1.5,2.5,0))
        self.assertIsNone(s.observe("a",1.52,2.5,0.1))
        self.assertEqual(s.observe("a",1.5,2.5,0.21).column,1)
        self.assertIsNone(s.observe("a",1.5,2.5,0.3))

    def test_occlusion_requires_new_settling(self):
        s=Stabilizer(10,10)
        s.observe("a",1.5,2.5,0)
        s.missing("a")
        self.assertIsNone(s.observe("a",1.5,2.5,1))
        self.assertFalse(s.confirmed)

    def test_offboard_and_same_cell_objects(self):
        s=Stabilizer(10,10)
        self.assertIsNone(s.observe("a",-1,2,0))
        for identity in ("a","b"):
            for t in (0,0.1,0.21):
                s.observe(identity,1.5,2.5,t)
        self.assertEqual(s.confirmed,{"a":(1,2),"b":(1,2)})

    def test_drift_resets_even_inside_cell(self):
        s=Stabilizer(10,10)
        for t,x in ((0,1.1),(0.1,1.3),(0.2,1.5),(0.3,1.7)):
            self.assertIsNone(s.observe("a",x,2.5,t))

    def test_long_gap_does_not_count_as_stable(self):
        s=Stabilizer(10,10)
        s.observe("a",1.5,2.5,0)
        self.assertIsNone(s.observe("a",1.5,2.5,2))

if __name__ == "__main__":
    unittest.main()
