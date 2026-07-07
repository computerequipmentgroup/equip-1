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
from .dvsource import DvSource
from .events import EventBus
from .models import CameraState, DaemonState, DeckState, ErrorState, RecordingState, StorageState
from .network import get_network_state
from .preview import MjpegPreview
from .recorder import RecordingTracker
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
        self.dv = DvSource(dvgrab_bin=dvgrab_bin)
        self.recorder = RecordingTracker(self.capture_dir, source=self.dv)
        self.ffmpeg_bin = ffmpeg_bin
        self.preview = MjpegPreview(self.dv, ffmpeg_bin=ffmpeg_bin)
        self.events = EventBus()
        self.host_url_port = host_url_port
        self._lock = asyncio.Lock()
        self._monitor_task: asyncio.Task | None = None
        self._usb_storage_task: asyncio.Task | None = None
        self._storage_switch_lock = asyncio.Lock()
        self.auto_storage_switch = os.environ.get("FIREHAT_AUTO_STORAGE_SWITCH", "1") not in {"0", "false", "False", "no"}
        self._auto_storage_cooldown_seconds = float(os.environ.get("FIREHAT_AUTO_STORAGE_COOLDOWN_SECONDS", "5"))
        self._last_auto_storage_attempt_at: dict[str, float] = {"usb": 0.0, "sd": 0.0}
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
        await self.preview.stop()
        await self.dv.stop()
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
            self._debug_log(f"start-recording requested timestamp={timestamp}")
            try:
                # The FireWire device is already held by the shared DV source, so
                # recording just opens a file on the live stream -- no preview
                # hand-off, no device acquisition, effectively instant.
                await self.dv.ensure_running(True)
                await asyncio.to_thread(self.recorder.start, timestamp)
                self._debug_log(f"recorder started filename={self.recorder.state.filename} pid={self.recorder.state.pid}")
                self.error = None
            except OSError as exc:
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
                self._debug_log(f"stop-recording requested filename={thumbnail_prefix} pid={self.recorder.state.pid}")
                await asyncio.to_thread(self.recorder.stop)
                self._debug_log(f"recorder stopped filename={thumbnail_prefix}")
                # Preview keeps running on the shared DV source; nothing to release.
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
            await self.preview.stop()
            # Release the FireWire device so USB disk mode / shutdown can unmount
            # and power down cleanly.
            await self.dv.stop()
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

    async def switch_storage_usb(self) -> dict[str, Any]:
        return await self._switch_storage("usb")

    async def switch_storage_sd(self) -> dict[str, Any]:
        return await self._switch_storage("sd")

    async def _switch_storage(self, target: str) -> dict[str, Any]:
        async with self._storage_switch_lock:
            await self._prepare_storage_switch()
            result = await asyncio.to_thread(
                subprocess.run,
                ["/usr/sbin/firehat-storage-switch", target],
                check=False,
                capture_output=True,
                text=True,
                timeout=90,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or f"Storage switch to {target} failed").strip()
                self.error = ErrorState(message="Storage switch failed", detail=detail)
                await self.publish_state()
                raise CommandError(detail)
            self.error = None
            state = await self.publish_state()
            await self.publish_captures()
            return state

    async def _prepare_storage_switch(self) -> None:
        async with self._lock:
            self._poll_recorder_unlocked()
            if self.recorder.state.active:
                raise CommandError("Stop recording before switching storage")
            if self._usb_transfer_active() or self._usb_storage_starting():
                raise CommandError("USB disk mode is active")
            # Stop the shared DV/preview subprocesses before the helper checks
            # for dvgrab. This avoids switching storage while any capture-related
            # process is still alive, without silently stopping an active recording.
            await self.preview.stop()
            await self.dv.stop()
            state = self._snapshot_unlocked().to_dict()
        await self.events.publish({"type": "state", "state": state})
        await asyncio.to_thread(subprocess.run, ["sync"], check=False, timeout=10)

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

    async def preview_stream(self):
        return await self._acquire_stream("mjpeg")

    async def mkv_stream(self):
        return await self._acquire_stream("mkv")

    async def _acquire_stream(self, kind: str):
        # MJPEG (browser preview) and Matroska (VLC/network players) share the
        # single FireWire claim and the preview busy-lock, so only one consumer
        # is ever active at a time.
        state = await self.snapshot()
        self._debug_log(f"{kind} stream requested mode={state['mode']} connected={state['camera']['connected']}", verbose=True)
        if state["mode"] == "usb_transfer":
            raise CommandError("Live streaming is not available in USB disk mode")
        if not state["camera"]["connected"]:
            raise CommandError("No DV camera detected")
        try:
            if self.preview.active:
                active_seconds = self.preview.active_seconds
                stale_after = float(os.environ.get("FIREHAT_PREVIEW_STALE_SECONDS", "12"))
                if active_seconds < stale_after:
                    raise CommandError(f"Stream already active ({active_seconds:.1f}s)")
                self._debug_log(f"stream active for {active_seconds:.1f}s; stopping stale stream")
                try:
                    await asyncio.wait_for(self.preview.stop(), timeout=4.0)
                    self._debug_log("stale stream stopped before new stream")
                except asyncio.TimeoutError:
                    self._debug_log("stale stream stop timed out; starting new stream anyway")
            # Both idle and recording preview read the same live DV stream; the
            # only difference is a lighter filter while recording so the browser
            # feed yields CPU to the capture write.
            await self.dv.ensure_running(True)
            recording = state["mode"] == "recording"
            if kind == "mkv":
                return self.preview.stream_mkv(recording=recording)
            return self.preview.stream(recording=recording)
        except Exception as exc:
            raise CommandError(str(exc)) from exc

    def preview_media_type(self) -> str:
        return self.preview.media_type

    def mkv_media_type(self) -> str:
        return self.preview.mkv_media_type

    def _debug_log(self, message: str, verbose: bool = False) -> None:
        if verbose and os.environ.get("FIREHAT_DEBUG_LOGS") != "1" and not Path("/data/.firehat-debug").exists():
            return
        try:
            stamp = datetime.now(timezone.utc).isoformat()
            with open("/data/firehatd-debug.log", "a", encoding="utf-8") as handle:
                handle.write(f"{stamp} {message}\n")
        except OSError:
            pass

    async def _generate_thumbnails(self, prefix: str) -> None:
        try:
            await asyncio.to_thread(self.storage.generate_thumbnails_for_prefix, prefix, self.ffmpeg_bin)
        except Exception as exc:
            print(f"Thumbnail generation failed for {prefix}: {exc}", flush=True)
        finally:
            await asyncio.to_thread(subprocess.run, ["sync"], check=False, timeout=10)
            # Re-publish so the web UI picks up the new thumbnail (or the capture
            # even if thumbnailing failed).
            await self.publish_captures()

    async def _monitor_loop(self) -> None:
        while True:
            try:
                async with self._lock:
                    self._poll_recorder_unlocked()
                    state = self._snapshot_unlocked().to_dict()
                # Keep the shared DV source claimed whenever a camera is present
                # (and we are not handing the bus/disk to USB mode), so recording
                # can start instantly on the already-flowing stream. Also stand
                # down while a USB-storage start is still in flight: that flag
                # only flips to "usb_transfer" once the helper succeeds, and the
                # helper refuses to run while dvgrab is alive -- so we must not
                # respawn the source in that window or we deadlock the hand-off.
                want_source = (
                    state["camera"]["connected"]
                    and state["mode"] != "usb_transfer"
                    and not self._usb_storage_starting()
                )
                try:
                    await self.dv.ensure_running(want_source)
                except Exception as exc:
                    self._debug_log(f"dv source ensure_running failed: {exc}")
                if state != self._last_state:
                    self._last_state = state
                    await self.events.publish({"type": "state", "state": state})
                await self._auto_switch_storage_if_needed(state)
            except Exception as exc:  # keep daemon alive even if probing fails
                async with self._lock:
                    self.error = ErrorState(message="Monitor failed", detail=str(exc))
                    state = self._snapshot_unlocked().to_dict()
                await self.events.publish({"type": "state", "state": state})
            await asyncio.sleep(1.0)

    def _poll_recorder_unlocked(self) -> None:
        if self.recorder.state.active:
            pid = self.recorder.state.pid
            rc = self.recorder.poll()
            if rc is not None:
                self.error = ErrorState(message="Recording stopped", detail=f"dvgrab exited with status {rc} (pid {pid})")

    async def _auto_switch_storage_if_needed(self, state: dict[str, Any]) -> None:
        if not self.auto_storage_switch or self._storage_switch_lock.locked():
            return
        if self._usb_storage_starting() or state.get("mode") in {"recording", "usb_transfer"}:
            return

        storage = state.get("storage") or {}
        kind = str(storage.get("device_kind") or "unknown")
        usb_present = self._usb_block_present()

        # If the active /data USB was pulled, restore the SD data partition.
        # This is deliberately skipped while recording; hot-swapping the capture
        # target underneath dvgrab is unsafe.
        if kind == "usb" and not usb_present:
            await self._auto_switch_storage("sd", "USB storage disappeared; switching back to SD")
            return

        # A newly inserted USB stick should become the capture volume when the
        # system is idle. The helper still enforces the unambiguous-exFAT rules.
        if usb_present and kind not in {"usb", "transfer"}:
            await self._auto_switch_storage("usb", "USB storage detected; switching to USB")

    async def _auto_switch_storage(self, target: str, reason: str) -> None:
        now = time.monotonic()
        if now - self._last_auto_storage_attempt_at.get(target, 0.0) < self._auto_storage_cooldown_seconds:
            return
        self._last_auto_storage_attempt_at[target] = now
        self._debug_log(f"auto storage: {reason}")
        try:
            await self._switch_storage(target)
        except Exception as exc:
            self._debug_log(f"auto storage switch to {target} failed: {exc}")

    @staticmethod
    def _usb_block_present() -> bool:
        return any(Path("/sys/block").glob("sd*"))

    def _usb_transfer_active(self) -> bool:
        return Path("/run/firehat-usb-storage.active").exists()

    def _usb_storage_starting(self) -> bool:
        # True from the moment start_usb_storage schedules its task until that
        # task finishes -- covering the window before the ".active" flag exists.
        return self._usb_storage_task is not None and not self._usb_storage_task.done()

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
                device="USB-C",
                device_kind="transfer",
                mount_point=None,
                filesystem_type=None,
            )
        else:
            snapshot = self.storage.snapshot()
            storage = StorageState(
                capture_dir=snapshot.capture_dir,
                total_bytes=snapshot.total_bytes,
                used_bytes=snapshot.used_bytes,
                free_bytes=snapshot.free_bytes,
                recording_minutes_available=snapshot.recording_minutes_available,
                device=snapshot.device,
                device_kind=snapshot.device_kind,
                mount_point=snapshot.mount_point,
                filesystem_type=snapshot.filesystem_type,
            )
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
            # Deck status/timecode is no longer polled: probing it ran dvcont
            # (AV/C transactions) on the FireWire bus every second, contending
            # with the shared DV stream, and nothing consumes those fields. The
            # on-demand transport commands (deck_command) still use dvcont.
            deck=DeckState(
                available=probe.connected,
                status="unknown",
                timecode=None,
                last_command=self.deck.last_command,
                error=self.deck.last_error,
            ),
            error=self.error,
        )
