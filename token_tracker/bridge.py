"""Authenticated loopback bridge. No Foundry credentials are needed."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import threading
import sys
import time
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, urlopen

MAX_BODY = 16384

class BridgeState:
    def __init__(self, scene_id, columns, rows, ttl=3.0):
        if not scene_id or not isinstance(columns, int) or not isinstance(rows, int) or columns < 1 or rows < 1:
            raise ValueError("Scene and positive integer grid dimensions required")
        self.scene_id, self.columns, self.rows = scene_id, columns, rows
        self.ttl, self.sequence = ttl, 0
        self.session = secrets.token_hex(16)
        self.latest = {}
        self.lock = threading.Lock()

    def publish(self, data):
        piece = data.get("piece_id")
        col, row = data.get("column"), data.get("row")
        if not isinstance(piece,str) or not piece or len(piece) > 128:
            raise ValueError("Invalid piece_id")
        if type(col) is not int or type(row) is not int or not (0 <= col < self.columns and 0 <= row < self.rows):
            raise ValueError("Move is outside the configured board")
        if data.get("scene_id") != self.scene_id:
            raise ValueError("Scene mismatch")
        if data.get("columns") != self.columns or data.get("rows") != self.rows:
            raise ValueError("Calibration grid mismatch")
        with self.lock:
            if piece not in self.latest and len(self.latest) >= 64:
                raise ValueError("Piece capacity exceeded")
            self.sequence += 1
            event = dict(piece_id=piece,column=col,row=row,sequence=self.sequence)
            self.latest[piece] = (event,time.monotonic())
            return self.sequence

    def snapshot(self, since=0):
        with self.lock:
            now = time.monotonic()
            events = [dict(event) for event,created in self.latest.values()
                      if event["sequence"] > since and now-created <= self.ttl]
            return dict(protocol=1,session=self.session,scene_id=self.scene_id,
                        columns=self.columns,rows=self.rows,sequence=self.sequence,
                        events=sorted(events,key=lambda event:event["sequence"]))

def make_server(state, token, origin, port=8765):
    if not token or len(token) < 16:
        raise ValueError("Bridge token must have at least 16 characters")
    parsed = urlsplit(origin)
    if parsed.scheme not in ("http","https") or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Specify an exact Foundry origin, without a path")
    origin = origin.rstrip("/")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def reply(self,status,data):
            payload = json.dumps(data).encode()
            self.send_response(status)
            if self.headers.get("Origin") == origin:
                self.send_header("Access-Control-Allow-Origin",origin)
                self.send_header("Vary","Origin")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def allowed_origin(self):
            requested = self.headers.get("Origin")
            return requested is None or requested == origin

        def authorized(self):
            return self.allowed_origin() and secrets.compare_digest(
                self.headers.get("Authorization", ""), "Bearer "+token)

        def do_OPTIONS(self):
            if self.headers.get("Origin") != origin:
                return self.reply(403,{"error":"Origin denied"})
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin",origin)
            self.send_header("Vary","Origin")
            self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers","Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Private-Network","true")
            self.end_headers()

        def do_GET(self):
            if not self.authorized():
                return self.reply(403,{"error":"Unauthorized"})
            parsed = urlsplit(self.path)
            if parsed.path != "/events":
                return self.reply(404,{"error":"Not found"})
            try:
                since = int(parse_qs(parsed.query).get("since",["0"])[0])
                if since < 0:
                    raise ValueError()
                self.reply(200,state.snapshot(since))
            except ValueError:
                self.reply(400,{"error":"Invalid cursor"})

        def do_POST(self):
            if not self.authorized():
                return self.reply(403,{"error":"Unauthorized"})
            if self.path != "/moves":
                return self.reply(404,{"error":"Not found"})
            try:
                length = int(self.headers.get("Content-Length","0"))
                if not 0 < length <= MAX_BODY:
                    return self.reply(413,{"error":"Invalid body size"})
                self.connection.settimeout(2)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data,dict):
                    raise ValueError("Object required")
                sequence = state.publish(data)
                self.reply(200,{"sequence":sequence})
            except (ValueError,TypeError,TimeoutError) as error:
                self.reply(400,{"error":str(error)})
    return ThreadingHTTPServer(("127.0.0.1",port),Handler)

class BridgePublisher:
    def __init__(self, url, token, scene_id, columns, rows):
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1","localhost") or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("Bridge must be an HTTP loopback URL")
        if not token or not scene_id:
            raise ValueError("Bridge token and scene ID are required")
        self.url,self.token,self.scene_id = url.rstrip("/"),token,scene_id
        self.columns,self.rows = columns,rows

    def publish(self,event):
        data = dict(piece_id=event.piece_id,column=event.column,row=event.row,
                    scene_id=self.scene_id,columns=self.columns,rows=self.rows)
        request = Request(self.url+"/moves",data=json.dumps(data).encode(),
                          headers={"Authorization":"Bearer "+self.token,"Content-Type":"application/json"})
        with urlopen(request,timeout=0.5) as response:
            return json.load(response)

class AsyncBridgePublisher:
    """Bounded latest-move retries without blocking camera inference."""
    def __init__(self,publisher,ttl=3.0):
        self.publisher,self.ttl = publisher,ttl
        self.pending,self.lock = {},threading.Lock()
        self.stopped = threading.Event()
        self.worker = threading.Thread(target=self._run,daemon=True)
        self.worker.start()

    def publish(self,event):
        with self.lock:
            self.pending[event.piece_id] = (event,time.monotonic())

    def _run(self):
        last_error = None
        while not self.stopped.wait(0.1):
            with self.lock:
                pending = list(self.pending.items())
            for piece,item in pending:
                event,created = item
                expired = time.monotonic()-created > self.ttl
                try:
                    if not expired:
                        self.publisher.publish(event)
                    with self.lock:
                        if self.pending.get(piece) == item:
                            self.pending.pop(piece,None)
                    last_error = None
                except Exception as error:
                    message = str(error)
                    if message != last_error:
                        print("Foundry bridge unavailable: "+message,file=sys.stderr)
                        last_error = message

    def close(self):
        self.stopped.set()
        self.worker.join(timeout=1)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command",required=True)
    serve = sub.add_parser("serve")
    move = sub.add_parser("move",help="Send a manual test move; no camera/model required")
    for p in (serve,move):
        p.add_argument("--scene-id",required=True)
        p.add_argument("--columns",type=int,required=True)
        p.add_argument("--rows",type=int,required=True)
    serve.add_argument("--origin",default="http://localhost:30000")
    serve.add_argument("--port",type=int,default=8765)
    move.add_argument("--bridge",default="http://127.0.0.1:8765")
    move.add_argument("--piece-id",required=True)
    move.add_argument("--column",type=int,required=True)
    move.add_argument("--row",type=int,required=True)
    args = parser.parse_args()
    token = os.environ.get("TOKEN_TRACKER_KEY")
    if args.command == "serve":
        token = token or secrets.token_urlsafe(32)
        state = BridgeState(args.scene_id,args.columns,args.rows)
        server = make_server(state,token,args.origin,args.port)
        print("Bridge token (enter in Foundry client settings): "+token,flush=True)
        print("Listening only on 127.0.0.1:"+str(server.server_port),flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    else:
        from .state import Movement
        publisher = BridgePublisher(args.bridge,token,args.scene_id,args.columns,args.rows)
        print(publisher.publish(Movement(args.piece_id,args.column,args.row,time.monotonic())))

if __name__ == "__main__":
    main()
