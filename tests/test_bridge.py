import json
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from token_tracker.bridge import BridgeState,BridgePublisher,make_server
from token_tracker.state import Movement

KEY="test-token-at-least-16-characters"
ORIGIN="http://localhost:30000"

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.state=BridgeState("scene",12,8)
        self.server=make_server(self.state,KEY,ORIGIN,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url="http://127.0.0.1:"+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def request(self,path,token=KEY,origin=ORIGIN,method="GET"):
        req=Request(self.url+path,headers={"Authorization":"Bearer "+token,"Origin":origin},method=method)
        return urlopen(req,timeout=2)

    def test_publish_poll_and_cursor(self):
        sender=BridgePublisher(self.url,KEY,"scene",12,8)
        sender.publish(Movement("goblin",3,4,0))
        with self.request("/events?since=0") as response:
            data=json.load(response)
            self.assertEqual(response.headers["Access-Control-Allow-Origin"],ORIGIN)
        self.assertEqual(data["events"][0]["column"],3)
        self.assertEqual(data["scene_id"],"scene")
        with self.request("/events?since=1") as response:
            self.assertEqual(json.load(response)["events"],[])

    def test_auth_and_origin(self):
        for token,origin in (("wrong",ORIGIN),(KEY,"https://evil.example")):
            with self.assertRaises(HTTPError) as error:
                self.request("/events",token,origin)
            self.assertEqual(error.exception.code,403)

    def test_preflight(self):
        with self.request("/events",method="OPTIONS") as response:
            self.assertEqual(response.status,204)
            self.assertEqual(response.headers["Access-Control-Allow-Origin"],ORIGIN)

    def test_reject_wrong_scene_grid_and_bounds(self):
        base=dict(piece_id="goblin",column=1,row=1,scene_id="scene",columns=12,rows=8)
        for change in ({"scene_id":"other"},{"columns":10},{"column":12},{"column":True}):
            with self.assertRaises(ValueError):
                self.state.publish(base|change)
        self.assertEqual(self.state.sequence,0)

    def test_latest_only_and_stale_expiration(self):
        base=dict(piece_id="goblin",column=1,row=1,scene_id="scene",columns=12,rows=8)
        self.state.publish(base)
        self.state.publish(base|{"column":2})
        self.assertEqual(len(self.state.snapshot()["events"]),1)
        self.state.ttl=-1
        self.assertEqual(self.state.snapshot()["events"],[])

    def test_loopback_only_publisher(self):
        with self.assertRaises(ValueError):
            BridgePublisher("http://example.com",KEY,"scene",12,8)

if __name__ == "__main__":
    unittest.main()
