"""Versioned dashboard calibration records, keyed by physical camera identity."""
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from .calibration import Calibration


def record_path(directory, identity):
    key = hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()
    return Path(directory) / ('camera-calibration-' + key + '.json')


def save(directory, identity, board):
    path = record_path(directory, identity)
    data = dict(version=1, camera_identity=identity, columns=board.columns, rows=board.rows,
                matrix=board.matrix.tolist(), image_size=board.image_size, residual_cells=board.residual_cells)
    # A failed or interrupted write must not corrupt the previous usable record.
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix='.calibration-', suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(data, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def restore(directory, identity, columns, rows, size):
    path = record_path(directory, identity)
    try:
        with path.open() as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
            raise ValueError('outdated calibration format')
        if data.get('camera_identity') != identity:
            raise ValueError('camera identity mismatch')
        board = Calibration.load(path)
        if (board.columns, board.rows) != (columns, rows):
            raise ValueError('board dimensions changed')
        if board.image_size != size:
            raise ValueError('actual image resolution changed')
        if (type(board.residual_cells) not in (int, float) or
                not math.isfinite(board.residual_cells) or not 0 <= board.residual_cells <= 0.15):
            raise ValueError('invalid calibration residual')
        return board, 'Restored saved calibration; verify grid alignment before tracking.'
    except FileNotFoundError:
        reason = 'no saved calibration for this camera (legacy view files are not reused)'
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        reason = 'saved calibration is invalid, outdated, or incompatible'
    return None, reason + '; freeze a frame and save a new calibration.'
