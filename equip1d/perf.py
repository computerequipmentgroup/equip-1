from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

_PERF_FLAG = Path("/data/.equip1-perf")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def enabled() -> bool:
    return _truthy(os.environ.get("EQUIP1_PERF_LOGS")) or _PERF_FLAG.exists()


def threshold_ms(default: float = 25.0) -> float:
    try:
        return max(0.0, float(os.environ.get("EQUIP1_PERF_THRESHOLD_MS", str(default))))
    except ValueError:
        return default


def log_elapsed(name: str, started: float, *, threshold: float | None = None, **fields: Any) -> None:
    if not enabled():
        return
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    limit = threshold_ms() if threshold is None else threshold
    if elapsed_ms < limit:
        return
    extras = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    suffix = f" {extras}" if extras else ""
    print(f"[PERF] {name} {elapsed_ms:.1f}ms{suffix}", flush=True)
