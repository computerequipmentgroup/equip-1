from __future__ import annotations

import os

_LEVELS = {
    "quiet": 0,
    "error": 1,
    "warn": 2,
    "warning": 2,
    "info": 3,
    "debug": 4,
}


def log_level(default: str = "info") -> str:
    raw = os.environ.get("EQUIP1_LOG_LEVEL", default).strip().lower()
    return raw if raw in _LEVELS else default


def should_log(level: str = "info") -> bool:
    current = _LEVELS[log_level()]
    wanted = _LEVELS.get(level.strip().lower(), _LEVELS["info"])
    return current >= wanted


def debug_enabled() -> bool:
    return should_log("debug")


def perf_enabled() -> bool:
    return should_log("debug")


def log(message: str, level: str = "info") -> None:
    if should_log(level):
        print(message, flush=True)
