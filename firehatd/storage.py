from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

DV_BYTES_PER_MINUTE = 216 * 1024 * 1024
CAPTURE_EXTENSIONS = {".dv", ".avi", ".mov", ".mp4", ".mkv"}


@dataclass(frozen=True)
class StorageSnapshot:
    capture_dir: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    recording_minutes_available: int


class StorageManager:
    def __init__(self, capture_dir: str | os.PathLike[str]):
        self.capture_dir = Path(capture_dir).expanduser()
        self.capture_dir.mkdir(parents=True, exist_ok=True)

    def snapshot(self) -> StorageSnapshot:
        total, used, free = shutil.disk_usage(self.capture_dir)
        return StorageSnapshot(
            capture_dir=str(self.capture_dir),
            total_bytes=total,
            used_bytes=used,
            free_bytes=free,
            recording_minutes_available=int(free / DV_BYTES_PER_MINUTE),
        )

    def has_recording_space(self, minimum_minutes: int = 1) -> bool:
        return self.snapshot().recording_minutes_available >= minimum_minutes

    def list_captures(self) -> list[dict]:
        captures: list[dict] = []
        for path in sorted(self.capture_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_file() or path.suffix.lower() not in CAPTURE_EXTENSIONS:
                continue
            stat = path.stat()
            captures.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "download_url": f"/api/captures/{path.name}/download",
                }
            )
        return captures

    def capture_path(self, name: str) -> Path | None:
        if not name or name != Path(name).name:
            return None
        path = self.capture_dir / name
        try:
            resolved_dir = self.capture_dir.resolve()
            resolved_path = path.resolve()
        except OSError:
            return None
        if resolved_path.parent != resolved_dir:
            return None
        if not resolved_path.is_file() or resolved_path.suffix.lower() not in CAPTURE_EXTENSIONS:
            return None
        return resolved_path
