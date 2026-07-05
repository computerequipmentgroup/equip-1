from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class RecorderProcessState:
    active: bool = False
    filename: str | None = None
    started_at_monotonic: float | None = None
    started_at_iso: str | None = None
    pid: int | None = None


class RecordingTracker:
    """Owns the dvgrab recording process and recording metadata."""

    def __init__(self, capture_dir: str | os.PathLike[str], dvgrab_bin: str = "dvgrab"):
        self.capture_dir = Path(capture_dir).expanduser()
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.dvgrab_bin = dvgrab_bin
        self.state = RecorderProcessState()
        self.process: subprocess.Popen | None = None
        self.log_handle = None

    def capture_prefix(self, timestamp: str) -> Path:
        return self.capture_dir / f"capture_{timestamp}"

    def start(self, timestamp: str | None = None) -> RecorderProcessState:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("Already recording")
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        prefix = self.capture_prefix(timestamp)
        log_path = prefix.with_suffix(".dvgrab.log")
        self.log_handle = log_path.open("ab", buffering=0)
        command = [self.dvgrab_bin, "-buffers", "50", "-size", "0", str(prefix)]
        self.process = subprocess.Popen(
            command,
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.state = RecorderProcessState(
            active=True,
            filename=prefix.name,
            started_at_monotonic=time.monotonic(),
            started_at_iso=datetime.now(timezone.utc).isoformat(),
            pid=self.process.pid,
        )
        return self.state

    def stop(self, timeout: float = 2.0) -> RecorderProcessState:
        proc = self.process
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait(timeout=2.0)
        self.process = None
        if self.log_handle is not None:
            try:
                self.log_handle.close()
            finally:
                self.log_handle = None
        subprocess.run(["sync"], check=False, timeout=10)
        self.state = RecorderProcessState()
        return self.state

    def poll(self) -> int | None:
        proc = self.process
        if proc is None:
            return None
        rc = proc.poll()
        if rc is not None:
            if self.log_handle is not None:
                try:
                    self.log_handle.close()
                finally:
                    self.log_handle = None
            self.process = None
            self.state = RecorderProcessState()
        return rc

    def elapsed_seconds(self) -> int:
        if not self.state.active or self.state.started_at_monotonic is None:
            return 0
        return int(time.monotonic() - self.state.started_at_monotonic)
