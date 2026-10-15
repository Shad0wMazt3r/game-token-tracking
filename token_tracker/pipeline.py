"""Shared deterministic board-observation pipeline for replay and the dashboard."""
from dataclasses import asdict
import math
from .fusion import BoardObservation, fuse
from .state import Stabilizer


class Pipeline:
    def __init__(self, columns, rows, **options):
        self.columns, self.rows = columns, rows
        self.state = Stabilizer(columns, rows, options.get("settle_ms", 200) / 1000,
                                options.get("tolerance_cells", 0.12), options.get("max_gap_ms", 500) / 1000)
        self.options = dict(max_age=options.get("max_age_ms", 300) / 1000,
                            max_uncertainty=options.get("max_uncertainty_cells", 0.35),
                            disagreement=options.get("disagreement_cells", 0.4))
        self.processed = {}
        self.last_time = -math.inf

    def reset(self):
        self.state.pending.clear()
        self.state.confirmed.clear()
        self.processed.clear()

    def step(self, now, observations):
        if not math.isfinite(now) or now < self.last_time:
            raise ValueError("Frame times must be finite and chronological")
        self.last_time = now
        positions, ambiguous = fuse(observations, now, self.columns, self.rows, **self.options)
        events = []
        for piece, (x, y, timestamp) in positions.items():
            if timestamp <= self.processed.get(piece, -math.inf):
                continue
            self.processed[piece] = timestamp
            event = self.state.observe(piece, x, y, timestamp)
            if event:
                events.append(asdict(event) | {"emitted_at": now, "observation_age_ms": (now - timestamp) * 1000})
        for piece in list(self.state.pending):
            if piece not in positions:
                self.state.missing(piece)
        return {"events": events, "ambiguous": sorted(ambiguous), "usable": len(positions),
                "confirmed": {key: list(value) for key, value in self.state.confirmed.items()}}


def replay(frames, columns, rows, **options):
    """Frames contain complete board-space snapshots, including empty/failed views."""
    pipeline = Pipeline(columns, rows, **options)
    for frame in frames:
        if not isinstance(frame, dict) or not isinstance(frame.get("observations"), list):
            raise ValueError("Each replay frame needs time and an observations list")
        observations = [BoardObservation(**item) for item in frame["observations"]]
        yield pipeline.step(frame["time"], observations)
