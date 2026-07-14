from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import perf
from .camera import FireWireCameraDetector
from .deck import DeckCommand, DeckControlError, DvcontDeckController
from .dvmetadata import stamp_file_from_dv_recording_date
from .dvsource import DvSource
from .events import EventBus
from .logging import debug_enabled, log
from .models import CameraState, CaptureNamingState, DaemonState, DeckState, ErrorState, LightsState, RecordingState, StorageState
from .network import get_network_state
from .preview import MjpegPreview
from .recorder import RecordingTracker
from .storage import StorageManager
from .settings import (
    CAPTURE_FILENAME_PREFIX_DEFAULT,
    CAPTURE_FILENAME_TEMPLATE_DEFAULT,
    Equip1Settings,
    LEGACY_LIGHTS_CONFIG_DEFAULT,
    LIGHTS_BRIGHTNESS_DEFAULT,
)


class CommandError(RuntimeError):
    pass


def _coerce_rgb(color: Any) -> list[int] | None:
    """Normalize a client-supplied color into a clamped [r, g, b] list, or
    None when it cannot be interpreted."""
    if isinstance(color, dict):
        values = [color.get("r"), color.get("g"), color.get("b")]
    elif isinstance(color, (list, tuple)):
        values = list(color[:3])
    else:
        return None
    if len(values) != 3:
        return None
    rgb: list[int] = []
    for value in values:
        try:
            channel = int(value)
        except (TypeError, ValueError):
            return None
        rgb.append(max(0, min(255, channel)))
    return rgb


LIGHTS_COUNT_DEFAULT = 3
_FILENAME_UNSAFE_RE = re.compile(r"[\\/:*?\"<>|\s]+")
_TAG_RE = re.compile(r"\{([a-zA-Z_]+)\}")


def _coerce_colors(value: Any, count: int) -> list[list[int]] | None:
    """Normalize a client payload into `count` [r, g, b] triples. Accepts a
    single color (applied to every LED) or a list of per-LED colors."""
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], (list, tuple, dict)):
        colors: list[list[int]] = []
        for item in value:
            rgb = _coerce_rgb(item)
            if rgb is None:
                return None
            colors.append(rgb)
        # Pad short lists with the last color and truncate long ones so the
        # stored length always matches the LED count.
        return [list(colors[i] if i < len(colors) else colors[-1]) for i in range(count)]

    single = _coerce_rgb(value)
    if single is None:
        return None
    return [list(single) for _ in range(count)]


def _lights_count_from_env() -> int:
    try:
        return max(1, int(os.environ.get("EQUIP1_LIGHTS_COUNT", str(LIGHTS_COUNT_DEFAULT))))
    except ValueError:
        return LIGHTS_COUNT_DEFAULT


def _coerce_brightness(value: Any) -> float | None:
    try:
        brightness = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, brightness))


def _light_colors_from_env(count: int) -> list[list[int]]:
    base = [0, 0, 255]
    raw = os.environ.get("EQUIP1_LIGHTS_DEFAULT_COLOR")
    if raw:
        parsed = _coerce_rgb([part.strip() for part in raw.split(",")])
        if parsed is not None:
            base = parsed
    return [list(base) for _ in range(count)]


def _clean_capture_naming_value(value: Any, default: str, max_length: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        return default
    cleaned = value.replace("\x00", "").strip()
    if not cleaned:
        return "" if allow_empty else default
    return cleaned[:max_length]


def _filename_tag_values(recorded_at: datetime) -> dict[str, str]:
    return {
        "date": recorded_at.strftime("%Y%m%d"),
        "time": recorded_at.strftime("%H%M%S"),
        "datetime": recorded_at.strftime("%Y%m%d_%H%M%S"),
        "year": recorded_at.strftime("%Y"),
        "month": recorded_at.strftime("%m"),
        "day": recorded_at.strftime("%d"),
        "hour": recorded_at.strftime("%H"),
        "minute": recorded_at.strftime("%M"),
        "second": recorded_at.strftime("%S"),
    }


def _sanitize_filename_stem(value: str) -> str:
    stem = _FILENAME_UNSAFE_RE.sub("_", value).strip("._-")
    stem = re.sub(r"_+", "_", stem)
    if not stem:
        stem = _render_capture_filename_stem(
            CAPTURE_FILENAME_PREFIX_DEFAULT,
            CAPTURE_FILENAME_TEMPLATE_DEFAULT,
            datetime.now(timezone.utc),
        )
    return stem[:120].strip("._-") or "capture"


def _render_capture_filename_stem(prefix: str, template: str, recorded_at: datetime) -> str:
    tags = _filename_tag_values(recorded_at)

    def replace_tag(match: re.Match[str]) -> str:
        return tags.get(match.group(1).lower(), "")

    raw = f"{prefix}{_TAG_RE.sub(replace_tag, template)}"
    return _sanitize_filename_stem(raw)


class Equip1Daemon:
    def __init__(
        self,
        capture_dir: str | os.PathLike[str],
        host_url_port: int = 8000,
        dvgrab_bin: str = "dvgrab",
        dvcont_bin: str = "dvcont",
        ffmpeg_bin: str = "ffmpeg",
        settings: Equip1Settings | None = None,
    ):
        self.settings = settings or Equip1Settings()
        self.capture_dir = Path(capture_dir).expanduser()
        self.storage = StorageManager(self.capture_dir)
        self.camera = FireWireCameraDetector()
        self.deck = DvcontDeckController(dvcont_bin=dvcont_bin)
        self.dv = DvSource(dvgrab_bin=dvgrab_bin)
        self.recorder = RecordingTracker(self.capture_dir, source=self.dv)
        self.ffmpeg_bin = ffmpeg_bin
        self.preview = MjpegPreview(self.dv, ffmpeg_bin=ffmpeg_bin, settings=self.settings)
        self.events = EventBus()
        self.host_url_port = host_url_port
        self._lock = asyncio.Lock()
        self._monitor_task: asyncio.Task | None = None
        self._usb_storage_task: asyncio.Task | None = None
        self._storage_switch_lock = asyncio.Lock()
        self.auto_storage_switch = self.settings.get_bool(
            "recording", "auto_storage_switch", True, env="EQUIP1_AUTO_STORAGE_SWITCH"
        )
        self._auto_storage_cooldown_seconds = self.settings.get_float(
            "recording", "auto_storage_cooldown_seconds", 5.0, env="EQUIP1_AUTO_STORAGE_COOLDOWN_SECONDS"
        )
        self._last_auto_storage_attempt_at: dict[str, float] = {"usb": 0.0, "sd": 0.0}
        self._last_state: dict[str, Any] | None = None
        self._last_captures_storage_key: tuple[Any, ...] | None = None
        self._storage_snapshot_cache: tuple[float, Any] | None = None
        self._storage_snapshot_ttl = self.settings.get_float(
            "performance", "storage_snapshot_ttl", 0.75, env="EQUIP1_STORAGE_SNAPSHOT_TTL"
        )
        self._captures_cache: tuple[float, list[dict]] | None = None
        self._captures_cache_ttl = self.settings.get_float(
            "performance", "captures_cache_ttl", 2.0, env="EQUIP1_CAPTURES_CACHE_TTL"
        )
        self._legacy_lights_config_path = Path(
            os.environ.get("EQUIP1_LIGHTS_CONFIG", LEGACY_LIGHTS_CONFIG_DEFAULT)
        ).expanduser()
        self._lights_count = _lights_count_from_env()
        self.lights_default_colors, self.lights_enabled, self.lights_brightness = self._load_light_settings()
        self.capture_naming_prefix, self.capture_naming_template = self._load_capture_naming()
        self.error: ErrorState | None = None

    @classmethod
    def from_env(cls) -> "Equip1Daemon":
        settings = Equip1Settings()
        capture_dir = settings.get("recording", "capture_dir", "~/captures", env="EQUIP1_CAPTURE_DIR") or "~/captures"
        port = settings.get_int("network", "port", 8000, env="EQUIP1_PORT")
        dvgrab_bin = os.environ.get("EQUIP1_DVGRAB_BIN", "dvgrab")
        dvcont_bin = os.environ.get("EQUIP1_DVCONT_BIN", "dvcont")
        ffmpeg_bin = os.environ.get("EQUIP1_FFMPEG_BIN", "ffmpeg")
        return cls(
            capture_dir=capture_dir,
            host_url_port=port,
            dvgrab_bin=dvgrab_bin,
            dvcont_bin=dvcont_bin,
            ffmpeg_bin=ffmpeg_bin,
            settings=settings,
        )

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
        started = time.perf_counter()
        async with self._lock:
            state = self._snapshot_unlocked().to_dict()
        perf.log_elapsed("daemon.snapshot", started)
        return state

    async def publish_state(self) -> dict[str, Any]:
        started = time.perf_counter()
        state = await self.snapshot()
        await self.events.publish({"type": "state", "state": state})
        perf.log_elapsed("daemon.publish_state", started)
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
            try:
                # The FireWire device is already held by the shared DV source, so
                # recording just opens a file on the live stream -- no preview
                # hand-off, no device acquisition, effectively instant.
                await self.dv.ensure_running(True)
                recorded_at = await self._recording_datetime(now)
                filename_stem = self._render_capture_filename_stem(recorded_at)
                self._debug_log(f"start-recording requested filename_stem={filename_stem}")
                await asyncio.to_thread(self.recorder.start, filename_stem=filename_stem)
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
                recorded_at = await asyncio.to_thread(
                    stamp_file_from_dv_recording_date,
                    self.capture_dir / thumbnail_prefix,
                )
                if recorded_at is not None:
                    self._captures_cache = None
                    self._debug_log(f"recorder stamped filename={thumbnail_prefix} recorded_at={recorded_at.isoformat()}")
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

    async def _recording_datetime(self, fallback: datetime) -> datetime:
        if not self._system_clock_unset():
            return fallback
        recorded_at = await self._wait_for_dv_recording_datetime()
        if recorded_at is None:
            return fallback
        self._debug_log(f"using DV camera date for filename recorded_at={recorded_at.isoformat()}")
        return recorded_at

    def _render_capture_filename_stem(self, recorded_at: datetime) -> str:
        return _render_capture_filename_stem(
            self.capture_naming_prefix,
            self.capture_naming_template,
            recorded_at,
        )

    async def _wait_for_dv_recording_datetime(self, timeout: float = 1.5) -> datetime | None:
        deadline = time.monotonic() + timeout
        while True:
            recorded_at = self.dv.latest_recording_datetime
            if recorded_at is not None:
                return recorded_at
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.05)

    @staticmethod
    def _system_clock_unset() -> bool:
        return time.time() < 1_600_000_000

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
                log(f"Time sync failed: {exc}", level="warning")
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
            # Release the FireWire device so USB disk mode can unmount cleanly.
            await self.dv.stop()
            self._poll_recorder_unlocked()
            state = self._snapshot_unlocked().to_dict()
        await self.events.publish({"type": "state", "state": state})
        await asyncio.to_thread(subprocess.run, ["sync"], check=False, timeout=10)

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
                ["/usr/sbin/equip1-usb-storage", "start"],
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
        self._storage_snapshot_cache = None
        self._captures_cache = None
        state = await self.publish_state()
        await self.publish_captures_for_state(state)

    async def stop_usb_storage(self) -> dict[str, Any]:
        result = await asyncio.to_thread(
            subprocess.run,
            ["/usr/sbin/equip1-usb-storage", "stop"],
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
        self._storage_snapshot_cache = None
        self._captures_cache = None
        state = await self.publish_state()
        await self.publish_captures_for_state(state)
        return state

    def _load_light_settings(self) -> tuple[list[list[int]], bool, float]:
        fallback = _light_colors_from_env(self._lights_count)
        loaded = self.settings.load_lights(
            count=self._lights_count,
            fallback_colors=fallback,
            coerce_colors=_coerce_colors,
        )
        if loaded is not None:
            return loaded
        return self._load_legacy_light_settings(fallback)

    def _load_legacy_light_settings(self, fallback: list[list[int]]) -> tuple[list[list[int]], bool, float]:
        try:
            data = json.loads(self._legacy_lights_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return fallback, True, LIGHTS_BRIGHTNESS_DEFAULT
        payload = data.get("default_colors") if isinstance(data, dict) else data
        colors = _coerce_colors(payload, self._lights_count)
        enabled = bool(data.get("enabled", True)) if isinstance(data, dict) else True
        brightness = _coerce_brightness(data.get("brightness")) if isinstance(data, dict) else None
        return (colors if colors is not None else fallback), enabled, (brightness if brightness is not None else LIGHTS_BRIGHTNESS_DEFAULT)

    def _save_light_settings(self) -> None:
        try:
            self.settings.save_lights(
                colors=self.lights_default_colors,
                enabled=self.lights_enabled,
                brightness=self.lights_brightness,
            )
        except OSError as exc:
            self._debug_log(f"could not save settings to {self.settings.path}: {exc}")

    def _load_capture_naming(self) -> tuple[str, str]:
        prefix, template = self.settings.load_capture_naming()
        return (
            _clean_capture_naming_value(prefix, CAPTURE_FILENAME_PREFIX_DEFAULT, 48, allow_empty=True),
            _clean_capture_naming_value(template, CAPTURE_FILENAME_TEMPLATE_DEFAULT, 96),
        )

    def _save_capture_naming(self) -> None:
        try:
            self.settings.save_capture_naming(
                prefix=self.capture_naming_prefix,
                template=self.capture_naming_template,
            )
        except OSError as exc:
            self._debug_log(f"could not save settings to {self.settings.path}: {exc}")

    async def set_capture_naming(self, prefix: Any, template: Any) -> dict[str, Any]:
        next_prefix = _clean_capture_naming_value(prefix, CAPTURE_FILENAME_PREFIX_DEFAULT, 48, allow_empty=True)
        next_template = _clean_capture_naming_value(template, CAPTURE_FILENAME_TEMPLATE_DEFAULT, 96)
        async with self._lock:
            self.capture_naming_prefix = next_prefix
            self.capture_naming_template = next_template
            state = self._snapshot_unlocked().to_dict()
        await asyncio.to_thread(self._save_capture_naming)
        await self.events.publish({"type": "state", "state": state})
        return state

    async def set_light_color(self, payload: Any) -> dict[str, Any]:
        colors = _coerce_colors(payload, self._lights_count)
        if colors is None:
            raise CommandError("Invalid light color")
        async with self._lock:
            self.lights_default_colors = colors
            state = self._snapshot_unlocked().to_dict()
        await asyncio.to_thread(self._save_light_settings)
        await self.events.publish({"type": "state", "state": state})
        return state

    async def set_lights_enabled(self, enabled: bool) -> dict[str, Any]:
        async with self._lock:
            self.lights_enabled = bool(enabled)
            state = self._snapshot_unlocked().to_dict()
        await asyncio.to_thread(self._save_light_settings)
        await self.events.publish({"type": "state", "state": state})
        return state

    async def set_lights_brightness(self, brightness: Any) -> dict[str, Any]:
        value = _coerce_brightness(brightness)
        if value is None:
            raise CommandError("Invalid light brightness")
        async with self._lock:
            self.lights_brightness = value
            state = self._snapshot_unlocked().to_dict()
        await asyncio.to_thread(self._save_light_settings)
        await self.events.publish({"type": "state", "state": state})
        return state

    async def switch_storage_usb(self) -> dict[str, Any]:
        return await self._switch_storage("usb")

    async def switch_storage_sd(self) -> dict[str, Any]:
        return await self._switch_storage("sd")

    async def _switch_storage(self, target: str, publish_pre_state: bool = True) -> dict[str, Any]:
        async with self._storage_switch_lock:
            await self._prepare_storage_switch(publish_pre_state=publish_pre_state)
            result = await asyncio.to_thread(
                subprocess.run,
                ["/usr/sbin/equip1-storage-switch", target],
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
            self._storage_snapshot_cache = None
            self._captures_cache = None
            state = await self.publish_state()
            await self.publish_captures_for_state(state)
            return state

    async def _prepare_storage_switch(self, publish_pre_state: bool = True) -> None:
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
        if publish_pre_state:
            await self.events.publish({"type": "state", "state": state})
        await asyncio.to_thread(subprocess.run, ["sync"], check=False, timeout=10)

    async def list_captures(self) -> list[dict]:
        return await self._list_captures_cached()

    async def _list_captures_cached(self, *, force: bool = False) -> list[dict]:
        now = time.monotonic()
        if not force and self._captures_cache is not None:
            cached_at, captures = self._captures_cache
            if now - cached_at <= self._captures_cache_ttl:
                return [dict(capture) for capture in captures]

        started = time.perf_counter()
        captures = await asyncio.to_thread(self.storage.list_captures)
        perf.log_elapsed("storage.list_captures", started)
        self._captures_cache = (now, [dict(capture) for capture in captures])
        return captures

    async def publish_captures(self) -> list[dict]:
        captures = await self._list_captures_cached(force=True)
        await self.events.publish({"type": "captures", "captures": captures})
        return captures

    async def publish_captures_for_state(self, state: dict[str, Any]) -> list[dict]:
        self._last_captures_storage_key = self._captures_storage_key(state)
        if state.get("mode") == "usb_transfer":
            captures: list[dict] = []
            self._captures_cache = (time.monotonic(), [])
        else:
            captures = await self._list_captures_cached(force=True)
        await self.events.publish({"type": "captures", "captures": captures})
        return captures

    async def publish_captures_if_storage_changed(self, state: dict[str, Any]) -> list[dict] | None:
        key = self._captures_storage_key(state)
        if key == self._last_captures_storage_key:
            return None
        return await self.publish_captures_for_state(state)

    @staticmethod
    def _captures_storage_key(state: dict[str, Any]) -> tuple[Any, ...]:
        storage = state.get("storage") or {}
        return (
            state.get("mode") == "usb_transfer",
            storage.get("capture_dir"),
            storage.get("device"),
            storage.get("device_kind"),
            storage.get("mount_point"),
            storage.get("filesystem_type"),
            storage.get("total_bytes"),
        )

    async def capture_path(self, name: str) -> Path | None:
        return await asyncio.to_thread(self.storage.capture_path, name)

    async def thumbnail_path(self, name: str) -> Path | None:
        return await asyncio.to_thread(self.storage.thumbnail_path, name)

    async def preview_stream(self):
        return await self._acquire_stream("mjpeg")

    async def mkv_stream(self, takeover: bool = False):
        return await self._acquire_stream("mkv", takeover=takeover)

    async def _acquire_stream(self, kind: str, takeover: bool = False):
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
                stale_after = float(os.environ.get("EQUIP1_PREVIEW_STALE_SECONDS", "12"))
                if active_seconds < stale_after and not takeover:
                    raise CommandError(f"Stream already active ({active_seconds:.1f}s)")
                reason = "takeover" if takeover else "stale"
                self._debug_log(f"stream active for {active_seconds:.1f}s; stopping {reason} stream")
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
        if verbose and not debug_enabled():
            return
        try:
            stamp = datetime.now(timezone.utc).isoformat()
            log_path = Path(os.environ.get("EQUIP1_DAEMON_DEBUG_LOG", "/var/log/equip1/daemon-debug.log"))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{stamp} {message}\n")
        except OSError:
            pass

    async def _generate_thumbnails(self, prefix: str) -> None:
        try:
            await asyncio.to_thread(self.storage.generate_thumbnails_for_prefix, prefix, self.ffmpeg_bin)
        except Exception as exc:
            log(f"Thumbnail generation failed for {prefix}: {exc}", level="warning")
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
                switched = await self._auto_switch_storage_if_needed(state)
                if not switched:
                    await self.publish_captures_if_storage_changed(state)
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

    async def _auto_switch_storage_if_needed(self, state: dict[str, Any]) -> bool:
        if not self.auto_storage_switch or self._storage_switch_lock.locked():
            return False
        if self._usb_storage_starting() or state.get("mode") in {"recording", "usb_transfer"}:
            return False

        storage = state.get("storage") or {}
        kind = str(storage.get("device_kind") or "unknown")
        usb_present = self._usb_block_present()

        # If the active /data USB was pulled, restore the SD data partition.
        # This is deliberately skipped while recording; hot-swapping the capture
        # target underneath dvgrab is unsafe.
        if kind == "usb" and not usb_present:
            return await self._auto_switch_storage("sd", "USB storage disappeared; switching back to SD")

        # A newly inserted USB stick should become the capture volume when the
        # system is idle. The helper still enforces the unambiguous-exFAT rules.
        if usb_present and kind not in {"usb", "transfer"}:
            return await self._auto_switch_storage("usb", "USB storage detected; switching to USB")
        return False

    async def _auto_switch_storage(self, target: str, reason: str) -> bool:
        now = time.monotonic()
        if now - self._last_auto_storage_attempt_at.get(target, 0.0) < self._auto_storage_cooldown_seconds:
            return False
        self._last_auto_storage_attempt_at[target] = now
        self._debug_log(f"auto storage: {reason}")
        try:
            await self._switch_storage(target, publish_pre_state=False)
            return True
        except Exception as exc:
            self._debug_log(f"auto storage switch to {target} failed: {exc}")
            return False

    @staticmethod
    def _usb_block_present() -> bool:
        return any(Path("/sys/block").glob("sd*"))

    def _usb_transfer_active(self) -> bool:
        return Path("/run/equip1-usb-storage.active").exists()

    def _usb_storage_starting(self) -> bool:
        # True from the moment start_usb_storage schedules its task until that
        # task finishes -- covering the window before the ".active" flag exists.
        return self._usb_storage_task is not None and not self._usb_storage_task.done()

    def _storage_snapshot_cached(self):
        now = time.monotonic()
        if self._storage_snapshot_cache is not None:
            cached_at, snapshot = self._storage_snapshot_cache
            if now - cached_at <= self._storage_snapshot_ttl:
                return snapshot
        started = time.perf_counter()
        snapshot = self.storage.snapshot()
        perf.log_elapsed("storage.snapshot", started)
        self._storage_snapshot_cache = (now, snapshot)
        return snapshot

    def _snapshot_unlocked(self) -> DaemonState:
        started = time.perf_counter()
        self._poll_recorder_unlocked()
        usb_transfer_active = self._usb_transfer_active()
        probe_started = time.perf_counter()
        probe = self.camera.probe()
        perf.log_elapsed("camera.probe", probe_started)
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
            snapshot = self._storage_snapshot_cached()
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

        network_started = time.perf_counter()
        network = get_network_state(self.host_url_port)
        perf.log_elapsed("network.state", network_started)
        state = DaemonState(
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
            network=network,
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
            lights=LightsState(
                default_colors=[list(color) for color in self.lights_default_colors],
                enabled=self.lights_enabled,
                brightness=self.lights_brightness,
            ),
            capture_naming=CaptureNamingState(
                prefix=self.capture_naming_prefix,
                template=self.capture_naming_template,
            ),
            error=self.error,
        )
        perf.log_elapsed("daemon.snapshot_unlocked", started)
        return state
