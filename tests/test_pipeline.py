import unittest
from token_tracker.fusion import BoardObservation
from token_tracker.pipeline import Pipeline, replay


def observation(time, x=1.5, y=2.5, camera="left", **changes):
    return BoardObservation(**(dict(piece_id="goblin_1", x=x, y=y, confidence=0.9,
                                    uncertainty=0.03, camera=camera, timestamp=time) | changes))


class PipelineTests(unittest.TestCase):
    def test_stable_movement_and_no_duplicate(self):
        pipeline = Pipeline(12, 8)
        results = [pipeline.step(t, [observation(t)]) for t in (0, .1, .25, .35)]
        self.assertEqual(sum(len(r["events"]) for r in results), 1)
        self.assertEqual(results[2]["events"][0]["column"], 1)
        self.assertEqual(results[3]["confirmed"], {"goblin_1": [1, 2]})

    def test_missing_and_conflict_hold_confirmed(self):
        pipeline = Pipeline(12, 8)
        for t in (0, .1, .25):
            pipeline.step(t, [observation(t)])
        self.assertEqual(pipeline.step(.3, [])["confirmed"], {"goblin_1": [1, 2]})
        result = pipeline.step(.4, [observation(.4), observation(.4, x=4.5, camera="right")])
        self.assertEqual(result["ambiguous"], ["goblin_1"])
        self.assertEqual(result["events"], [])
        self.assertEqual(result["confirmed"], {"goblin_1": [1, 2]})

    def test_stale_offboard_uncertain_and_future_views_rejected(self):
        for obs in (observation(0), observation(1, x=-1), observation(1, uncertainty=1), observation(2)):
            pipeline = Pipeline(12, 8)
            self.assertEqual(pipeline.step(1, [obs])["usable"], 0)

    def test_one_clear_view_survives_disconnected_other_camera(self):
        pipeline = Pipeline(12, 8)
        for t in (1, 1.1, 1.25):
            result = pipeline.step(t, [observation(t), observation(0, x=9, camera="right")])
        self.assertEqual(len(result["events"]), 1)

    def test_gap_resets_pending_and_resync_reemits(self):
        pipeline = Pipeline(12, 8)
        pipeline.step(0, [observation(0)])
        self.assertEqual(pipeline.step(1, [observation(1)])["events"], [])
        self.assertEqual(len(pipeline.step(1.25, [observation(1.25)])["events"]), 1)
        pipeline.reset()
        pipeline.step(2, [observation(2)])
        self.assertEqual(len(pipeline.step(2.25, [observation(2.25)])["events"]), 1)

    def test_replay_deterministic_and_bad_clock_rejected(self):
        frames = [{"time": t, "observations": [observation(t).__dict__]} for t in (0, .1, .25)]
        self.assertEqual(list(replay(frames, 12, 8)), list(replay(frames, 12, 8)))
        with self.assertRaises(ValueError):
            list(replay(list(reversed(frames)), 12, 8))
        with self.assertRaises(ValueError):
            list(replay([{"time": 0}], 12, 8))

    def test_duplicate_camera_identity_is_ambiguous(self):
        result = Pipeline(12, 8).step(1, [observation(1), observation(1)])
        self.assertEqual(result["ambiguous"], ["goblin_1"])
