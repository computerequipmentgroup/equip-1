from __future__ import annotations

import glob
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraProbe:
    connected: bool
    device: str | None = None
    name: str | None = None


class FireWireCameraDetector:
    """Detect a DV camera exposed by the Linux FireWire stack."""

    def __init__(self, device_glob: str = "/dev/fw*"):
        self.device_glob = device_glob

    def probe(self) -> CameraProbe:
        devices = sorted(glob.glob(self.device_glob))
        # /dev/fw0 is commonly the host controller; a connected camera usually
        # appears as /dev/fw1 or higher.
        camera_devices = [path for path in devices if not path.endswith("fw0")]
        if not camera_devices:
            return CameraProbe(connected=False)
        return CameraProbe(
            connected=True,
            device=camera_devices[0],
            name="DV Camera",
        )
