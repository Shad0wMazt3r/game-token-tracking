"""Conservative fusion in board coordinates; no inferred identity swaps."""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class BoardObservation:
    piece_id: str
    x: float
    y: float
    confidence: float
    uncertainty: float
    camera: str
    timestamp: float

def fuse(observations, now, columns, rows, max_age=0.3, max_uncertainty=0.35, disagreement=0.4):
    grouped = {}
    for o in observations:
        if not all(math.isfinite(v) for v in (o.x,o.y,o.confidence,o.uncertainty,o.timestamp)):
            continue
        if not (0 <= now-o.timestamp <= max_age and 0 <= o.uncertainty <= max_uncertainty and 0 < o.confidence <= 1):
            continue
        if not (0 <= o.x < columns and 0 <= o.y < rows):
            continue
        grouped.setdefault(o.piece_id,[]).append(o)
    fused, ambiguous = {},set()
    for piece, views in grouped.items():
        if len({o.camera for o in views}) != len(views):
            ambiguous.add(piece); continue
        if any(math.hypot(a.x-b.x,a.y-b.y)>disagreement for i,a in enumerate(views) for b in views[i+1:]):
            ambiguous.add(piece); continue
        weights=[o.confidence/(o.uncertainty**2+0.01) for o in views]
        total=sum(weights)
        fused[piece]=(sum(o.x*w for o,w in zip(views,weights))/total,
                      sum(o.y*w for o,w in zip(views,weights))/total,max(o.timestamp for o in views))
    return fused,ambiguous
