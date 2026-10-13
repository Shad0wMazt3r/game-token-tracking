import unittest
from token_tracker.evaluate import evaluate

class EvaluationTests(unittest.TestCase):
    def test_correct_wrong_and_missed_moves(self):
        truth=[dict(piece_id="a",column=1,row=1,settled_at=1),dict(piece_id="b",column=2,row=2,settled_at=2),dict(piece_id="c",column=3,row=3,settled_at=3)]
        predictions=[dict(piece_id="a",column=1,row=1,emitted_at=1.25),dict(piece_id="b",column=5,row=5,emitted_at=2.2)]
        report=evaluate(truth,predictions)
        self.assertEqual((report["correct"],report["wrong"],report["missed"]),(1,1,1))
        self.assertEqual(report["p50_correct_emission_ms"],250)

    def test_next_trial_limits_matching_window(self):
        truth=[dict(piece_id="a",column=1,row=1,settled_at=1),dict(piece_id="a",column=2,row=2,settled_at=2)]
        prediction=[dict(piece_id="a",column=2,row=2,emitted_at=2.2)]
        report=evaluate(truth,prediction)
        self.assertEqual(report["correct"],1);self.assertEqual(report["missed"],1)
