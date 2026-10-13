import unittest
from token_tracker.fusion import BoardObservation,fuse
from token_tracker.state import Stabilizer

class FusionTests(unittest.TestCase):
    def observation(self,camera="left",x=3.5,y=2.5,t=1,uncertainty=0.05):
        return BoardObservation("goblin",x,y,0.9,uncertainty,camera,t)

    def test_single_camera_fallback(self):
        positions,ambiguous=fuse([self.observation()],1.1,12,8)
        self.assertAlmostEqual(positions["goblin"][0],3.5)
        self.assertFalse(ambiguous)

    def test_agreement_and_disagreement(self):
        a=self.observation();b=self.observation("right",x=3.6)
        positions,_=fuse([a,b],1.1,12,8)
        self.assertAlmostEqual(positions["goblin"][0],3.55)
        positions,ambiguous=fuse([a,self.observation("right",x=5.5)],1.1,12,8)
        self.assertFalse(positions);self.assertIn("goblin",ambiguous)

    def test_stale_and_uncertain_views_do_not_override_clear_view(self):
        observations=[self.observation(),self.observation("right",x=10,t=0)]
        positions,_=fuse(observations,1.1,12,8)
        self.assertAlmostEqual(positions["goblin"][0],3.5)
        positions,_=fuse([self.observation(uncertainty=1)],1.1,12,8)
        self.assertFalse(positions)

    def test_two_camera_move_becomes_one_confirmed_event(self):
        state=Stabilizer(12,8,max_gap=0.5);events=[]
        for t in (1,1.1,1.21,1.3):
            positions,_=fuse([self.observation(t=t),self.observation("right",x=3.52,t=t)],t+0.01,12,8)
            x,y,timestamp=positions["goblin"];event=state.observe("goblin",x,y,timestamp)
            if event:events.append(event)
        self.assertEqual(len(events),1);self.assertEqual((events[0].column,events[0].row),(3,2))
