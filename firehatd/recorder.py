from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RecorderProcessState:
    active: bool = False
    filename: str | None = None
    started_at_monotonic: float | None = None
    started_at_iso: str | None = None
    pid: int | None = None


class RecorderError(RuntimeError):
    pass


class DvgrabRecorder:
    """Owns the dvgrab subprocess for exactly one active recording."""

    def __init__(self, capture_dir: str | os.PathLike[str], dvgrab_bin: str = "dvgrab"):
        self.capture_dir = Path(capture_dir).expanduser()
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.dvgrab_bin = dvgrab_bin
        self.process: subprocess.Popen | None = None
        self._log_handle = None
        self.state = RecorderProcessState()

    def start(self, timestamp: str, started_at_iso: str) -> RecorderProcessState:
        if self.process and self.process.poll() is None:
            raise RecorderError("Recording is already active")

        prefix = self.capture_dir / f"capture_{timestamp}-"
        log_path = self.capture_dir / f"capture_{timestamp}.dvgrab.log"
        self._log_handle = open(log_path, "ab", buffering=0)
        try:
            self.process = subprocess.Popen(
                [self.dvgrab_bin, "-buffers", "20", str(prefix)],
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            self._close_log()
            raise RecorderError(f"Could not start {self.dvgrab_bin}: {exc}") from exc

        self.state = RecorderProcessState(
            active=True,
            filename=prefix.name,
            started_at_monotonic=time.monotonic(),
            started_at_iso=started_at_iso,
            pid=self.process.pid,
        )
        return self.state

    def stop(self, timeout: float = 5.0) -> RecorderProcessState:
        if not self.process:
            self.state = RecorderProcessState()
            return self.state

        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=2)

        self.process = None
        self._close_log()
        self.state = RecorderProcessState()
        return self.state

    def poll_error(self) -> str | None:
        if not self.process:
            return None
        code = self.process.poll()
        if code is None:
            return None
        self.process = None
        self._close_log()
        self.state = RecorderProcessState()
        if code == 0:
            return None
        return f"dvgrab exited with status {code}"

    def elapsed_seconds(self) -> int:
        if not self.state.active or self.state.started_at_monotonic is None:
            return 0
        return int(time.monotonic() - self.state.started_at_monotonic)

    def _close_log(self) -> None:
        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None
