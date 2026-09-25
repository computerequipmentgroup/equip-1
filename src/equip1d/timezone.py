from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TIMEZONE_DEFAULT = "Europe/Berlin"
TIMEZONE_OPTIONS = (
    "UTC",
    "Europe/Berlin",
    "Europe/London",
    "America/New_York",
    "America/Los_Angeles",
    "Asia/Tokyo",
)

# POSIX TZ fallbacks avoid depending on /usr/share/zoneinfo in the minimal
# Buildroot image. The signs are POSIX-style: CET-1 means UTC+1.
_POSIX_TZ = {
    "UTC": "UTC0",
    "Europe/Berlin": "CET-1CEST,M3.5.0/2,M10.5.0/3",
    "Europe/London": "GMT0BST,M3.5.0/1,M10.5.0/2",
    "America/New_York": "EST5EDT,M3.2.0/2,M11.1.0/2",
    "America/Los_Angeles": "PST8PDT,M3.2.0/2,M11.1.0/2",
    "Asia/Tokyo": "JST-9",
}

_TZ_LOCK = threading.Lock()


def normalize_timezone(value: str | None) -> str:
    raw = (value or TIMEZONE_DEFAULT).strip()
    aliases = {
        "": TIMEZONE_DEFAULT,
        "local": TIMEZONE_DEFAULT,
        "berlin": "Europe/Berlin",
        "cet": "Europe/Berlin",
        "cest": "Europe/Berlin",
        "london": "Europe/London",
        "uk": "Europe/London",
        "new_york": "America/New_York",
        "new-york": "America/New_York",
        "nyc": "America/New_York",
        "los_angeles": "America/Los_Angeles",
        "los-angeles": "America/Los_Angeles",
        "la": "America/Los_Angeles",
        "tokyo": "Asia/Tokyo",
        "japan": "Asia/Tokyo",
        "z": "UTC",
        "gmt": "UTC",
        "utc": "UTC",
    }
    lowered = raw.lower()
    normalized = aliases.get(lowered, raw)
    return normalized if normalized in TIMEZONE_OPTIONS else TIMEZONE_DEFAULT


def timezone_label(value: str | None) -> str:
    timezone = normalize_timezone(value)
    return {
        "UTC": "UTC",
        "Europe/Berlin": "Berlin",
        "Europe/London": "London",
        "America/New_York": "New York",
        "America/Los_Angeles": "Los Angeles",
        "Asia/Tokyo": "Tokyo",
    }.get(timezone, timezone)


def timezone_env(value: str | None) -> str:
    return _POSIX_TZ[normalize_timezone(value)]


def apply_process_timezone(value: str | None) -> str:
    timezone = normalize_timezone(value)
    os.environ["TZ"] = timezone_env(timezone)
    if hasattr(time, "tzset"):
        time.tzset()
    return timezone


@contextmanager
def _temporary_tz(tz: str):
    with _TZ_LOCK:
        previous = os.environ.get("TZ")
        os.environ["TZ"] = tz
        if hasattr(time, "tzset"):
            time.tzset()
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            if hasattr(time, "tzset"):
                time.tzset()


def local_datetime(value: str | None, epoch_seconds: float | None = None) -> tuple[datetime, str]:
    timezone = normalize_timezone(value)
    epoch = time.time() if epoch_seconds is None else epoch_seconds
    try:
        tzinfo = ZoneInfo(timezone)
        dt = datetime.fromtimestamp(epoch, tzinfo)
        return dt, dt.strftime("%Z") or timezone_label(timezone)
    except ZoneInfoNotFoundError:
        pass

    with _temporary_tz(timezone_env(timezone)):
        local = time.localtime(epoch)
        dt = datetime(*local[:6])
        is_dst = local.tm_isdst > 0
        abbr = time.tzname[1 if is_dst and len(time.tzname) > 1 else 0]
        return dt, abbr or timezone_label(timezone)
