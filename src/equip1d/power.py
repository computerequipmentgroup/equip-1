from __future__ import annotations

import socket
import time
from pathlib import Path

from .models import PowerState
from .settings import Equip1Settings


PISUGAR_SOCKET_DEFAULT = "/tmp/pisugar-server.sock"


class PiSugarPowerMonitor:
    """Best-effort reader for pisugar-server's Unix-domain socket API.

    The monitor is intentionally optional: if pisugar-server is not installed,
    not running, or the PiSugar board is absent, snapshots report power as
    unavailable and the UI simply omits the battery indicator.
    """

    def __init__(self, settings: Equip1Settings):
        self.enabled = settings.get_bool("power", "pisugar_enabled", True, env="EQUIP1_PISUGAR_ENABLED")
        self.socket_path = Path(
            settings.get("power", "pisugar_socket", PISUGAR_SOCKET_DEFAULT, env="EQUIP1_PISUGAR_SOCKET")
            or PISUGAR_SOCKET_DEFAULT
        )
        self.poll_interval = max(
            0.25,
            settings.get_float("power", "pisugar_poll_interval", 5.0, env="EQUIP1_PISUGAR_POLL_INTERVAL"),
        )
        self.timeout = max(
            0.01,
            settings.get_float("power", "pisugar_timeout", 0.075, env="EQUIP1_PISUGAR_TIMEOUT"),
        )
        self._cache: tuple[float, PowerState] | None = None

    def snapshot(self) -> PowerState:
        if not self.enabled:
            return PowerState(source="pisugar", available=False)

        now = time.monotonic()
        if self._cache is not None:
            cached_at, cached_state = self._cache
            if now - cached_at <= self.poll_interval:
                return cached_state

        state = self._read_state()
        self._cache = (now, state)
        return state

    def _read_state(self) -> PowerState:
        if not self.socket_path.exists():
            return PowerState(source="pisugar", available=False)

        battery_percent = _parse_number(self._query("get battery"))
        if battery_percent is None:
            return PowerState(source="pisugar", available=False)

        external_power = _parse_bool(self._query("get battery_power_plugged"))
        allow_charging = _parse_bool(self._query("get battery_allow_charging"))
        legacy_charging = _parse_bool(self._query("get battery_charging"))
        charging = None
        if external_power is not None and allow_charging is not None:
            charging = external_power and allow_charging
        elif legacy_charging is not None:
            charging = legacy_charging

        return PowerState(
            source="pisugar",
            available=True,
            battery_percent=max(0, min(100, round(battery_percent))),
            external_power=external_power,
            charging=charging,
        )

    def _query(self, command: str) -> str | None:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(str(self.socket_path))
                sock.sendall(command.encode("utf-8") + b"\n")
                try:
                    sock.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                chunks: list[bytes] = []
                while True:
                    chunk = sock.recv(256)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", errors="replace").strip()
        except OSError:
            return None


def _response_value(response: str | None) -> str | None:
    if not response:
        return None
    line = response.strip().splitlines()[0].strip()
    if not line:
        return None
    if ":" in line:
        return line.split(":", 1)[1].strip()
    parts = line.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else None


def _parse_number(response: str | None) -> float | None:
    value = _response_value(response)
    if value is None:
        return None
    try:
        return float(value.split()[0].strip().rstrip("%"))
    except (ValueError, IndexError):
        return None


def _parse_bool(response: str | None) -> bool | None:
    value = _response_value(response)
    if value is None:
        return None
    normalized = value.split()[0].strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None
