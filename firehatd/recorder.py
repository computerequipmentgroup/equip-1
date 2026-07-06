from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .dvsource import DvSource


@dataclass
class RecorderProcessState:
    active: bool = False
    filename: str | None = None
    started_at_monotonic: float | None = None
    started_at_iso: str | None = None
    pid: int | None = None


class RecordingTracker:
    """Toggles the recording sink on the shared DV source and owns metadata.

    Recording no longer spawns its own dvgrab: the FireWire device is held
    continuously by the shared ``DvSource``, so starting a capture is just
    opening a file on the already-flowing stream. That makes record start
    effectively instant -- there is no preview hand-off or device acquisition.
    """

    def __init__(self, capture_dir: str | os.PathLike[str], source: DvSource):
        self.capture_dir = Path(capture_dir).expanduser()
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.source = source
        self.state = RecorderProcessState()
        self._intent = False

    def capture_prefix(self, timestamp: str) -> Path:
        return self.capture_dir / f"capture_{timestamp}"

    def start(self, timestamp: str | None = None) -> RecorderProcessState:
        if self.state.active:
            raise RuntimeError("Already recording")
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self.capture_prefix(timestamp).with_suffix(".dv")
        self.source.start_recording(path)
        self._intent = True
        self.state = RecorderProcessState(
            active=True,
            filename=path.name,
            started_at_monotonic=time.monotonic(),
            started_at_iso=datetime.now(timezone.utc).isoformat(),
            pid=self.source._proc.pid if self.source._proc is not None else None,
        )
        return self.state

    def stop(self, timeout: float = 2.0) -> RecorderProcessState:
        self._intent = False
        self.source.stop_recording()
        subprocess.run(["sync"], check=False, timeout=10)
        self.state = RecorderProcessState()
        return self.state

    def poll(self) -> int | None:
        # Surfaces an unexpected loss of the recording (e.g. dvgrab died or a
        # disk write failed) the same way the old dvgrab-exit poll did.
        if self._intent and not self.source.recording:
            self._intent = False
            self.state = RecorderProcessState()
            return 1
        return None

    def elapsed_seconds(self) -> int:
        if not self.state.active or self.state.started_at_monotonic is None:
            return 0
        return int(time.monotonic() - self.state.started_at_monotonic)
