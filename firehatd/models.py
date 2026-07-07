from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal

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
class DaemonState:
    mode: RecorderMode
    camera: CameraState
    recording: RecordingState
    storage: StorageState
    network: NetworkState
    deck: DeckState
    error: ErrorState | None = None
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)
