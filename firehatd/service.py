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
        ffmpeg_bin: str = "ffmpeg",
    ):
        self.capture_dir = Path(capture_dir).expanduser()
        self.storage = StorageManager(self.capture_dir)
        self.camera = FireWireCameraDetector()
        self.deck = DvcontDeckController(dvcont_bin=dvcont_bin)
        self.recorder = DvgrabRecorder(self.capture_dir, dvgrab_bin=dvgrab_bin)
        self.ffmpeg_bin = ffmpeg_bin
        self.events = EventBus()
        self.host_url_port = host_url_port
        self._lock = asyncio.Lock()
        self._monitor_task: asyncio.Task | None = None
        self._usb_storage_task: asyncio.Task | None = None
        self._last_state: dict[str, Any] | None = None
        self.error: ErrorState | None = None

    @classmethod
    def from_env(cls) -> "FirehatDaemon":
        capture_dir = os.environ.get("FIREHAT_CAPTURE_DIR", "~/captures")
        port = int(os.environ.get("FIREHAT_PORT", "8000"))
        dvgrab_bin = os.environ.get("FIREHAT_DVGRAB_BIN", "dvgrab")
        dvcont_bin = os.environ.get("FIREHAT_DVCONT_BIN", "dvcont")
        ffmpeg_bin = os.environ.get("FIREHAT_FFMPEG_BIN", "ffmpeg")
        return cls(capture_dir=capture_dir, host_url_port=port, dvgrab_bin=dvgrab_bin, dvcont_bin=dvcont_bin, ffmpeg_bin=ffmpeg_bin)

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
            if self._usb_transfer_active():
                raise CommandError("USB disk mode is active")
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
        thumbnail_prefix: str | None = None
        async with self._lock:
            if self.recorder.state.active:
                thumbnail_prefix = self.recorder.state.filename
                await asyncio.to_thread(self.recorder.stop)
            state = self._snapshot_unlocked().to_dict()
        await self.events.publish({"type": "state", "state": state})
        if thumbnail_prefix:
            # Push the freshly finished capture immediately, then push again once
            # its thumbnail has been rendered, so the web UI updates live.
            await self.publish_captures()
            asyncio.create_task(self._generate_thumbnails(thumbnail_prefix))
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

    async def sync_time(self, epoch_seconds: float) -> dict[str, Any]:
        # The device has no RTC and no network time, so it boots at the epoch and
        # captures get stamped 1980 (FAT default). A connected browser knows the
        # real time, so let it bootstrap the clock -- but only while the system
        # clock still looks unset, so a client with a wrong clock can't move an
        # already-correct one.
        applied = False
        current = time.time()
        # 1_600_000_000 == 2020-09-13; anything earlier means the clock is unset.
        if current < 1_600_000_000 and epoch_seconds > 1_600_000_000:
            try:
                await asyncio.to_thread(self._apply_system_time, epoch_seconds)
                applied = True
            except Exception as exc:
                print(f"Time sync failed: {exc}", flush=True)
        return {"applied": applied, "now": time.time()}

    def _apply_system_time(self, epoch_seconds: float) -> None:
        stamp = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        # BusyBox- and GNU-compatible: set the UTC system clock, then persist to
        # the RTC if one exists (harmless no-op otherwise).
        subprocess.run(["date", "-u", "-s", stamp], check=False, timeout=10)
        subprocess.run(["hwclock", "-w"], check=False, timeout=10)

    async def clear_error(self) -> dict[str, Any]:
        async with self._lock:
            self.error = None
            state = self._snapshot_unlocked().to_dict()
        await self.events.publish({"type": "state", "state": state})
        return state

    async def _prepare_power_transition(self) -> None:
        async with self._lock:
            if self.recorder.state.active:
                await asyncio.to_thread(self.recorder.stop)
            self._poll_recorder_unlocked()
            state = self._snapshot_unlocked().to_dict()
        await self.events.publish({"type": "state", "state": state})
        await asyncio.to_thread(subprocess.run, ["sync"], check=False, timeout=10)

    async def shutdown_host(self) -> dict[str, str]:
        await self._prepare_power_transition()
        command = ["shutdown", "-h", "now"] if os.geteuid() == 0 else ["sudo", "shutdown", "-h", "now"]
        subprocess.Popen(command)
        return {"status": "scheduled"}

    async def reboot_host(self) -> dict[str, str]:
        await self._prepare_power_transition()
        command = ["reboot"] if os.geteuid() == 0 else ["sudo", "reboot"]
        subprocess.Popen(command)
        return {"status": "scheduled"}

    async def start_usb_storage(self) -> dict[str, Any]:
        if self._usb_transfer_active():
            return await self.publish_state()
        if self._usb_storage_task and not self._usb_storage_task.done():
            return await self.publish_state()
        self._usb_storage_task = asyncio.create_task(self._run_usb_storage_start())
        return await self.publish_state()

    async def _run_usb_storage_start(self) -> None:
        try:
            await self._prepare_power_transition()
            result = await asyncio.to_thread(
                subprocess.run,
                ["/usr/sbin/firehat-usb-storage", "start"],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "USB disk mode failed").strip()
                self.error = ErrorState(message="USB disk failed", detail=detail)
            else:
                self.error = None
        except Exception as exc:
            self.error = ErrorState(message="USB disk failed", detail=str(exc))
        await self.publish_state()

    async def stop_usb_storage(self) -> dict[str, Any]:
        result = await asyncio.to_thread(
            subprocess.run,
            ["/usr/sbin/firehat-usb-storage", "stop"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "USB disk stop failed").strip()
            self.error = ErrorState(message="USB disk stop failed", detail=detail)
            raise CommandError(detail)
        self.error = None
        return await self.publish_state()

    async def list_captures(self) -> list[dict]:
        return await asyncio.to_thread(self.storage.list_captures)

    async def publish_captures(self) -> list[dict]:
        captures = await asyncio.to_thread(self.storage.list_captures)
        await self.events.publish({"type": "captures", "captures": captures})
        return captures

    async def capture_path(self, name: str) -> Path | None:
        return await asyncio.to_thread(self.storage.capture_path, name)

    async def thumbnail_path(self, name: str) -> Path | None:
        return await asyncio.to_thread(self.storage.thumbnail_path, name)

    async def _generate_thumbnails(self, prefix: str) -> None:
        try:
            await asyncio.to_thread(self.storage.generate_thumbnails_for_prefix, prefix, self.ffmpeg_bin)
        except Exception as exc:
            print(f"Thumbnail generation failed for {prefix}: {exc}", flush=True)
        finally:
            # Re-publish so the web UI picks up the new thumbnail (or the capture
            # even if thumbnailing failed).
            await self.publish_captures()

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

    def _usb_transfer_active(self) -> bool:
        return Path("/run/firehat-usb-storage.active").exists()

    def _snapshot_unlocked(self) -> DaemonState:
        self._poll_recorder_unlocked()
        usb_transfer_active = self._usb_transfer_active()
        probe = self.camera.probe()
        if usb_transfer_active:
            storage = StorageState(
                capture_dir=str(self.capture_dir),
                total_bytes=0,
                used_bytes=0,
                free_bytes=0,
                recording_minutes_available=0,
            )
        else:
            snapshot = self.storage.snapshot()
            storage = StorageState(
                capture_dir=snapshot.capture_dir,
                total_bytes=snapshot.total_bytes,
                used_bytes=snapshot.used_bytes,
                free_bytes=snapshot.free_bytes,
                recording_minutes_available=snapshot.recording_minutes_available,
            )
        deck = self.deck.probe(camera_connected=probe.connected)

        recording_active = self.recorder.state.active
        if usb_transfer_active:
            mode = "usb_transfer"
        elif self.error:
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
            storage=storage,
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
