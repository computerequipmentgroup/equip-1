from __future__ import annotations

import asyncio
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .camera import FireWireCameraDetector
from .deck import DeckCommand, DeckControlError, DvcontDeckController
from .events import EventBus
from .models import CameraState, DaemonState, DeckState, ErrorState, RecordingState, StorageState
from .network import get_network_state
from .recorder import DvgrabRecorder, RecorderError
from .storage import StorageManager


class CommandError(RuntimeError):
    pass


class FirehatDaemon:
    def __init__(
        self,
        capture_dir: str | os.PathLike[str],
        host_url_port: int = 8000,
        dvgrab_bin: str = "dvgrab",
        dvcont_bin: str = "dvcont",
    ):
        self.capture_dir = Path(capture_dir).expanduser()
        self.storage = StorageManager(self.capture_dir)
        self.camera = FireWireCameraDetector()
        self.deck = DvcontDeckController(dvcont_bin=dvcont_bin)
        self.recorder = DvgrabRecorder(self.capture_dir, dvgrab_bin=dvgrab_bin)
        self.events = EventBus()
        self.host_url_port = host_url_port
        self._lock = asyncio.Lock()
        self._monitor_task: asyncio.Task | None = None
        self._last_state: dict[str, Any] | None = None
        self.error: ErrorState | None = None

    @classmethod
    def from_env(cls) -> "FirehatDaemon":
        capture_dir = os.environ.get("FIREHAT_CAPTURE_DIR", "~/captures")
        port = int(os.environ.get("FIREHAT_PORT", "8000"))
        dvgrab_bin = os.environ.get("FIREHAT_DVGRAB_BIN", "dvgrab")
        dvcont_bin = os.environ.get("FIREHAT_DVCONT_BIN", "dvcont")
        return cls(capture_dir=capture_dir, host_url_port=port, dvgrab_bin=dvgrab_bin, dvcont_bin=dvcont_bin)

    async def start_monitor(self) -> None:
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop_monitor(self) -> None:
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

    async def shutdown(self) -> None:
        await self.stop_monitor()
        if self.recorder.state.active:
            await asyncio.to_thread(self.recorder.stop)
        await self.publish_state()

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return self._snapshot_unlocked().to_dict()

    async def publish_state(self) -> dict[str, Any]:
        state = await self.snapshot()
        await self.events.publish({"type": "state", "state": state})
        return state

    async def start_recording(self) -> dict[str, Any]:
        async with self._lock:
            self._poll_recorder_unlocked()
            if self.recorder.state.active:
                raise CommandError("Already recording")
            probe = self.camera.probe()
            if not probe.connected:
                raise CommandError("No DV camera detected")
            if not self.storage.has_recording_space(minimum_minutes=1):
                self.error = ErrorState(message="Storage full", detail="Less than one minute of DV recording space remains")
                raise CommandError("Storage full")

            now = datetime.now(timezone.utc)
            timestamp = now.strftime("%Y%m%d_%H%M%S")
            try:
                self.recorder.start(timestamp=timestamp, started_at_iso=now.isoformat())
                self.error = None
            except RecorderError as exc:
                self.error = ErrorState(message="Recorder failed", detail=str(exc))
                raise CommandError(str(exc)) from exc
            state = self._snapshot_unlocked().to_dict()
        await self.events.publish({"type": "state", "state": state})
        return state

    async def stop_recording(self) -> dict[str, Any]:
        async with self._lock:
            if self.recorder.state.active:
                await asyncio.to_thread(self.recorder.stop)
            state = self._snapshot_unlocked().to_dict()
        await self.events.publish({"type": "state", "state": state})
        return state

    async def rescan_camera(self) -> dict[str, Any]:
        return await self.publish_state()

    async def deck_command(self, command: DeckCommand) -> dict[str, Any]:
        async with self._lock:
            probe = self.camera.probe()
            if not probe.connected:
                raise CommandError("No DV camera detected")
            try:
                await asyncio.to_thread(self.deck.command, command)
                self.error = None
            except DeckControlError as exc:
                self.error = ErrorState(message="Deck command failed", detail=str(exc))
                raise CommandError(str(exc)) from exc
            state = self._snapshot_unlocked().to_dict()
        await self.events.publish({"type": "state", "state": state})
        return state

    async def clear_error(self) -> dict[str, Any]:
        async with self._lock:
            self.error = None
            state = self._snapshot_unlocked().to_dict()
        await self.events.publish({"type": "state", "state": state})
        return state

    async def shutdown_host(self) -> dict[str, str]:
        command = ["shutdown", "-h", "now"] if os.geteuid() == 0 else ["sudo", "shutdown", "-h", "now"]
        subprocess.Popen(command)
        return {"status": "scheduled"}

    async def reboot_host(self) -> dict[str, str]:
        command = ["reboot"] if os.geteuid() == 0 else ["sudo", "reboot"]
        subprocess.Popen(command)
        return {"status": "scheduled"}

    async def list_captures(self) -> list[dict]:
        return await asyncio.to_thread(self.storage.list_captures)

    async def _monitor_loop(self) -> None:
        while True:
            try:
                async with self._lock:
                    self._poll_recorder_unlocked()
                    state = self._snapshot_unlocked().to_dict()
                if state != self._last_state:
                    self._last_state = state
                    await self.events.publish({"type": "state", "state": state})
            except Exception as exc:  # keep daemon alive even if probing fails
                async with self._lock:
                    self.error = ErrorState(message="Monitor failed", detail=str(exc))
                    state = self._snapshot_unlocked().to_dict()
                await self.events.publish({"type": "state", "state": state})
            await asyncio.sleep(1.0)

    def _poll_recorder_unlocked(self) -> None:
        error = self.recorder.poll_error()
        if error:
            self.error = ErrorState(message="Recording stopped", detail=error)

    def _snapshot_unlocked(self) -> DaemonState:
        self._poll_recorder_unlocked()
        probe = self.camera.probe()
        storage = self.storage.snapshot()
        deck = self.deck.probe(camera_connected=probe.connected)

        recording_active = self.recorder.state.active
        if self.error:
            mode = "error"
        elif recording_active:
            mode = "recording"
        elif storage.recording_minutes_available < 1:
            mode = "storage_full"
        elif not probe.connected:
            mode = "no_camera"
        else:
            mode = "idle"

        return DaemonState(
            mode=mode,
            camera=CameraState(
                connected=probe.connected,
                name=probe.name,
                device=probe.device,
            ),
            recording=RecordingState(
                active=recording_active,
                filename=self.recorder.state.filename,
                started_at=self.recorder.state.started_at_iso,
                elapsed_seconds=self.recorder.elapsed_seconds(),
                pid=self.recorder.state.pid,
            ),
            storage=StorageState(
                capture_dir=storage.capture_dir,
                total_bytes=storage.total_bytes,
                used_bytes=storage.used_bytes,
                free_bytes=storage.free_bytes,
                recording_minutes_available=storage.recording_minutes_available,
            ),
            network=get_network_state(self.host_url_port),
            deck=DeckState(
                available=deck.available,
                status=deck.status,
                timecode=deck.timecode,
                last_command=self.deck.last_command,
                error=deck.error,
            ),
            error=self.error,
        )
