from __future__ import annotations


def hhmmss(seconds: int | float | None) -> str:
    total = int(seconds or 0)
    hh, rem = divmod(total, 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh:02}:{mm:02}:{ss:02}"


def bytes_gb(value: int | float | None) -> str:
    return f"{(value or 0) / (1024**3):.1f} GB"


def percent(used: int | float | None, total: int | float | None) -> int:
    if not total:
        return 0
    return int(((used or 0) / total) * 100)
