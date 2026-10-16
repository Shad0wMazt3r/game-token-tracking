"""Synthetic frames and fake serial identities; no physical camera claims."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
from token_tracker.bridge import BridgeState
from token_tracker.dashboard import Runtime
from token_tracker.calibration_store import record_path
from token_tracker.camera_identity import camera_identity

IDENTITY = ['usb-v1', 'serial-a', '1234', '5678', '00', '0']


class FakeCamera:
    identity_verified = True
    size = (640, 480)
    ready = True
    age = 0
    error = None

    def __init__(self, *args):
        pass

    def snapshot(self):
        if not self.ready:
            return None
        width, height = self.size
        return np.zeros((height, width, 3), dtype=np.uint8), 1, time.monotonic() - self.age

    def close(self):
        pass


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.camera = patch('token_tracker.capture.Camera', FakeCamera)
        self.camera.start()
        self.addCleanup(self.camera.stop)
        self.identity = patch('token_tracker.camera_identity.camera_identity', return_value=IDENTITY)
        self.lookup = self.identity.start()
        self.addCleanup(self.identity.stop)
        self.runtimes = []
        self.addCleanup(lambda: [r.close() for r in self.runtimes])
        self.path = record_path(self.directory.name, IDENTITY)

    def runtime(self, columns=12):
        runtime = Runtime(BridgeState('scene', columns, 8), self.directory.name)
        self.runtimes.append(runtime)
        return runtime

    def open(self, runtime, sources=(0,)):
        return runtime.open_cameras({'cameras': [{'source': s} for s in sources]})

    def calibrate(self, runtime, name='0'):
        runtime.frame(name, freeze=True)
        runtime.calibrate(dict(camera=name, image_points=[[0,0],[639,0],[639,479],[0,479]],
                               board_points=[[0,0],[12,0],[12,8],[0,8]]))

    def saved(self):
        runtime = self.runtime()
        self.open(runtime)
        self.calibrate(runtime)
        return runtime

    def test_restart_reopen_and_changed_index_restore(self):
        first = self.saved()
        self.assertTrue(self.open(first)['cameras'][0]['calibrated'])
        second = self.runtime()
        status = self.open(second, (4,))
        self.assertTrue(status['cameras'][0]['calibrated'])
        self.assertIn('Restored', status['cameras'][0]['calibration_status'])
        np.testing.assert_allclose(first.boards['0'].matrix, second.boards['0'].matrix)
        self.assertFalse(status['running'])

    def test_reordered_views_follow_identity(self):
        other = IDENTITY[:1] + ['serial-b'] + IDENTITY[2:]
        self.lookup.side_effect = lambda source: IDENTITY if source == 0 else other
        runtime = self.runtime()
        self.open(runtime, (0, 1))
        self.calibrate(runtime, '0')
        self.calibrate(runtime, '1')
        status = self.open(runtime, (1, 0))
        self.assertTrue(all(c['calibrated'] for c in status['cameras']))
        self.assertEqual(runtime.identities['1'], IDENTITY)

    def test_replacement_camera_and_unknown_identity_rejected(self):
        self.saved()
        for identity in (['different-camera'], None):
            with self.subTest(identity=identity):
                self.lookup.return_value = identity
                runtime = self.runtime()
                self.assertFalse(self.open(runtime)['cameras'][0]['calibrated'])
                self.assertIn('calibrat', runtime.calibration_status['0'])

    def test_missing_and_legacy_files_rejected(self):
        (Path(self.directory.name) / 'calibration-0.json').write_text('{}')
        runtime = self.runtime()
        self.assertFalse(self.open(runtime)['cameras'][0]['calibrated'])

    def test_board_and_actual_resolution_mismatch(self):
        self.saved()
        self.assertFalse(self.open(self.runtime(columns=10))['cameras'][0]['calibrated'])
        with patch.object(FakeCamera, 'size', (1280, 720)):
            self.assertFalse(self.open(self.runtime())['cameras'][0]['calibrated'])

    def test_waits_for_fresh_actual_frame(self):
        self.saved()
        runtime = self.runtime()
        with patch.object(FakeCamera, 'ready', False):
            self.assertFalse(self.open(runtime)['cameras'][0]['calibrated'])
        with patch.object(FakeCamera, 'age', 2):
            self.assertFalse(runtime.status()['cameras'][0]['calibrated'])
        self.assertTrue(runtime.status()['cameras'][0]['calibrated'])

    def test_malformed_outdated_and_invalid_records(self):
        self.saved()
        original = json.loads(self.path.read_text())
        cases = ['{', '[]', 'null']
        for key, value in [('version', 0), ('version', True), ('camera_identity', ['wrong']),
                           ('matrix', [[0]*3]*3), ('matrix', [[float('nan')]*3]*3),
                           ('columns', True), ('image_size', None), ('image_size', 42),
                           ('residual_cells', 'bad'), ('residual_cells', float('inf')),
                           ('residual_cells', -1), ('residual_cells', .2)]:
            cases.append(json.dumps(original | {key: value}))
        for contents in cases:
            with self.subTest(contents=contents):
                self.path.write_text(contents)
                runtime = self.runtime()
                self.assertFalse(self.open(runtime)['cameras'][0]['calibrated'])
                self.calibrate(runtime)
                self.assertTrue(self.open(runtime)['cameras'][0]['calibrated'])

    def test_unidentified_camera_session_only_and_duplicate_identity(self):
        self.lookup.return_value = None
        runtime = self.runtime()
        self.open(runtime)
        self.calibrate(runtime)
        self.assertIn('session', runtime.calibration_status['0'])
        self.assertFalse(self.path.exists())
        self.assertFalse(self.open(runtime)['cameras'][0]['calibrated'])
        self.lookup.return_value = IDENTITY
        self.assertTrue(all(not c['calibrated'] for c in self.open(runtime, (0, 1))['cameras']))

    def test_resolution_change_invalidates_active_board(self):
        runtime = self.saved()
        runtime.running = True
        with patch.object(FakeCamera, 'size', (800, 600)):
            status = runtime.status()
            self.assertFalse(status['running'])
            self.assertFalse(status['cameras'][0]['calibrated'])
            self.assertNotIn('0', runtime.previews)
            self.assertIn('resolution changed', runtime.calibration_status['0'])

    def test_non_v4l2_backend_cannot_use_sysfs_identity(self):
        with patch.object(FakeCamera, 'identity_verified', False):
            runtime = self.runtime()
            self.open(runtime)
            self.assertIsNone(runtime.identities['0'])

    def test_failed_save_preserves_record(self):
        runtime = self.saved()
        original = self.path.read_bytes()
        runtime.frame('0', freeze=True)
        with patch('token_tracker.calibration_store.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.calibrate(runtime)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(Path(self.directory.name).glob('*.tmp')), [])


class IdentityTests(unittest.TestCase):
    def test_serial_identity_survives_index_change_but_not_replacement(self):
        with tempfile.TemporaryDirectory() as directory, patch('sys.platform', 'linux'):
            root = Path(directory)
            usb = root / 'usb'
            interface = usb / 'interface'
            interface.mkdir(parents=True)
            for name, value in [('serial','abc'), ('idVendor','1234'), ('idProduct','5678')]:
                (usb / name).write_text(value)
            (interface / 'bInterfaceNumber').write_text('00')
            for index in (0, 4):
                node = root / ('video' + str(index))
                node.mkdir()
                (node / 'device').symlink_to(interface, target_is_directory=True)
                (node / 'index').write_text('0')
            identity = camera_identity(0, root)
            self.assertIsNotNone(identity)
            self.assertEqual(identity, camera_identity(4, root))
            (usb / 'serial').write_text('replacement')
            self.assertNotEqual(identity, camera_identity(0, root))
            (usb / 'serial').unlink()
            self.assertIsNone(camera_identity(0, root))
            self.assertIsNone(camera_identity(20, root))
        with patch('sys.platform', 'win32'):
            self.assertIsNone(camera_identity(0))
