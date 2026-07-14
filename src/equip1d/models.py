from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal

from .settings import CAPTURE_FILENAME_PREFIX_DEFAULT, CAPTURE_FILENAME_TEMPLATE_DEFAULT, LIGHTS_BRIGHTNESS_DEFAULT

RecorderMode = Literal[
    "booting",
    "no_camera",
    "idle",
    "recording",
    "stopping",
    "converting",
    "storage_full",
    "usb_transfer",
    "error",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CameraState:
    connected: bool = False
    name: str | None = None
    device: str | None = None


@dataclass
class RecordingState:
    active: bool = False
    filename: str | None = None
    started_at: str | None = None
    elapsed_seconds: int = 0
    pid: int | None = None


@dataclass
class StorageState:
    capture_dir: str
    total_bytes: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    recording_minutes_available: int = 0
    device: str | None = None
    device_kind: str = "unknown"
    mount_point: str | None = None
    filesystem_type: str | None = None


@dataclass
class NetworkState:
    ip: str | None = None
    hostname: str | None = None
    url: str | None = None
    mode: str = "offline"
    ssid: str | None = None
    password: str | None = None
    ap_ip: str | None = None
    iface: str | None = None


@dataclass
class DeckState:
    available: bool = False
    status: str = "unknown"
    timecode: str | None = None
    last_command: str | None = None
    error: str | None = None


@dataclass
class ErrorState:
    message: str
    detail: str | None = None
    at: str = field(default_factory=utc_now_iso)


@dataclass
class CaptureNamingState:
    prefix: str = CAPTURE_FILENAME_PREFIX_DEFAULT
    template: str = CAPTURE_FILENAME_TEMPLATE_DEFAULT


@dataclass
class LightsState:
    # Per-LED "standard" colors, one [r, g, b] per physical LED, authored at
    # full 0-255 brightness. Clients (OLED) dim each to the same level as the
    # fixed status colors before emitting. Defaults to full blue on every LED,
    # which dims to the no-camera blue.
    default_colors: list[list[int]] = field(
        default_factory=lambda: [[0, 0, 255], [0, 0, 255], [0, 0, 255]]
    )
    enabled: bool = True
    # Runtime brightness multiplier for normal/status LED output. Defaults to
    # a dim 25% level, while saved user settings can still override it.
    brightness: float = LIGHTS_BRIGHTNESS_DEFAULT


@dataclass
class DaemonState:
    mode: RecorderMode
    camera: CameraState
    recording: RecordingState
    storage: StorageState
    network: NetworkState
    deck: DeckState
    lights: LightsState = field(default_factory=LightsState)
    capture_naming: CaptureNamingState = field(default_factory=CaptureNamingState)
    error: ErrorState | None = None
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)
