"""Latest-frame capture prevents camera buffering from accumulating latency."""
import threading
import time
import cv2

class Camera:
    def __init__(self,source,width=1280,height=720):
        if type(source) is not int or source < 0:
            raise ValueError("Live session sources must be nonnegative webcam indices")
        self.capture=cv2.VideoCapture(source)
        if not self.capture.isOpened():
            self.capture.release()
            raise RuntimeError("Cannot open webcam "+str(source))
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH,width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT,height)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE,1)
        self.lock=threading.Lock(); self.latest=None; self.sequence=0
        self.error=None; self.stopped=threading.Event()
        self.worker=threading.Thread(target=self._read,daemon=True)
        self.worker.start()

    def _read(self):
        while not self.stopped.is_set():
            ok,frame=self.capture.read()
            if not ok:
                self.error="Camera stopped delivering frames"
                self.stopped.wait(0.05)
                continue
            with self.lock:
                self.sequence+=1
                self.latest=(frame,self.sequence,time.monotonic())
                self.error=None

    def snapshot(self):
        with self.lock:
            if self.latest is None: return None
            frame,sequence,timestamp=self.latest
            return frame.copy(),sequence,timestamp

    def close(self):
        self.stopped.set()
        self.worker.join(timeout=1)
        self.capture.release()
