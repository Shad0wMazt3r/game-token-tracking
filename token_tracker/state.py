"""Board-space stabilization; persistent piece IDs belong to the application."""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class Movement:
    piece_id: str
    column: int
    row: int
    observed_at: float

class Stabilizer:
    def __init__(self, columns, rows, settle_seconds=0.2, tolerance=0.12, max_gap=0.15):
        if columns < 1 or rows < 1 or settle_seconds < 0 or tolerance < 0 or max_gap <= 0:
            raise ValueError("Invalid grid or stability configuration")
        self.columns, self.rows = columns, rows
        self.settle_seconds, self.tolerance, self.max_gap = settle_seconds, tolerance, max_gap
        self.pending, self.confirmed = {}, {}

    def observe(self, piece_id, x, y, timestamp):
        if not all(math.isfinite(v) for v in (x, y, timestamp)):
            self.pending.pop(piece_id, None)
            return None
        if not (0 <= x < self.columns and 0 <= y < self.rows):
            self.pending.pop(piece_id, None)
            return None
        cell = (int(x), int(y))
        previous = self.pending.get(piece_id)
        if previous and timestamp < previous[4]:
            raise ValueError("Observations must be chronological")
        if (previous is None or previous[0] != cell
            or timestamp - previous[4] > self.max_gap
            or math.hypot(x - previous[1], y - previous[2]) > self.tolerance):
            self.pending[piece_id] = (cell, x, y, timestamp, timestamp)
            return None
        self.pending[piece_id] = (*previous[:4], timestamp)
        if timestamp - previous[3] >= self.settle_seconds and self.confirmed.get(piece_id) != cell:
            self.confirmed[piece_id] = cell
            return Movement(piece_id, *cell, timestamp)
        return None

    def missing(self, piece_id):
        self.pending.pop(piece_id, None)
