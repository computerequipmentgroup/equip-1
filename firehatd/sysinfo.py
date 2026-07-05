from __future__ import annotations

import os
from pathlib import Path


def get_system_stats() -> dict:
    cpu_count = os.cpu_count() or 1
    load_1m = _read_load_1m()
    cpu_percent = _clamp((load_1m / cpu_count) * 100 if load_1m is not None else 0)

    memory = _read_memory()
    temperature_c = _read_temperature_c()
    temperature_percent = _clamp((temperature_c / 85) * 100 if temperature_c is not None else 0)

    return {
        "model": _read_model(),
        "cpu": {
            "load_1m": load_1m,
            "count": cpu_count,
            "percent": cpu_percent,
        },
        "memory": memory,
        "temperature": {
            "celsius": temperature_c,
            "percent": temperature_percent,
        },
    }


def _read_load_1m() -> float | None:
    try:
        return float(Path("/proc/loadavg").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _read_memory() -> dict:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        values = {}

    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    used = max(0, total - available)
    percent = _clamp((used / total) * 100 if total else 0)
    return {
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": available,
        "percent": percent,
    }


def _read_temperature_c() -> float | None:
    candidates: list[tuple[int, float]] = []
    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        try:
            temp_raw = int((zone / "temp").read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        temp_c = temp_raw / 1000 if temp_raw > 1000 else float(temp_raw)
        if temp_c <= 0 or temp_c > 125:
            continue
        priority = 0
        try:
            zone_type = (zone / "type").read_text(encoding="utf-8").strip().lower()
            if any(token in zone_type for token in ("soc", "cpu", "gpu", "thermal")):
                priority = 1
        except OSError:
            pass
        candidates.append((priority, temp_c))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return round(candidates[0][1], 1)


def _read_model() -> str:
    for path in (Path("/proc/device-tree/model"), Path("/sys/firmware/devicetree/base/model")):
        try:
            model = path.read_text(encoding="utf-8", errors="ignore").replace("\x00", "").strip()
            if model:
                return model
        except OSError:
            pass
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith(("model", "hardware")) and ":" in line:
                value = line.split(":", 1)[1].strip()
                if value:
                    return value
    except OSError:
        pass
    return "ROCK compute"


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))
