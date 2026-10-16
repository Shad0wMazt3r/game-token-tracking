"""Conservative Linux V4L2 identities; enumeration indices are never identities."""
from pathlib import Path
import sys


def camera_identity(source, root=Path('/sys/class/video4linux')):
    """Return a serial-backed USB identity including the video interface.

    Unsupported platforms/devices deliberately return None. Model names and USB
    port paths alone cannot distinguish replacement cameras of the same model.
    """
    if not sys.platform.startswith('linux'):
        return None
    try:
        device = (root / ('video' + str(source)) / 'device').resolve(strict=True)
        interface = None
        for node in (device, *device.parents):
            if (node / 'bInterfaceNumber').is_file():
                interface = (node / 'bInterfaceNumber').read_text().strip()
            if all((node / name).is_file() for name in ('serial', 'idVendor', 'idProduct')):
                values = [(node / name).read_text().strip() for name in ('serial', 'idVendor', 'idProduct')]
                if all(values) and interface is not None:
                    # Multiple video nodes on one interface must remain distinct.
                    index = (root / ('video' + str(source)) / 'index').read_text().strip()
                    return ['usb-v1', *values, interface, index]
    except (OSError, RuntimeError):
        pass
    return None
