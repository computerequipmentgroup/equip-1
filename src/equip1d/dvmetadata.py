from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

NTSC_DV_FRAME_BYTES = 120_000
PAL_DV_FRAME_BYTES = 144_000
DIF_SEQUENCE_BYTES = 150 * 80
DV_AUDIO_RECORD_DATE_PACK = 0x52
DV_AUDIO_RECORD_TIME_PACK = 0x53
DV_VIDEO_RECORD_DATE_PACK = 0x62
DV_VIDEO_RECORD_TIME_PACK = 0x63
DEFAULT_SCAN_BYTES = PAL_DV_FRAME_BYTES * 20


def dv_frame_size(buffer: bytes | bytearray | memoryview) -> int:
    """Return the raw DV frame size implied by the DSF bit.

    Raw DV frames are 120000 bytes for 525/60 (NTSC) and 144000 bytes for
    625/50 (PAL). dvgrab uses byte 3 bit 7 to distinguish them.
    """

    if len(buffer) > 3 and buffer[3] & 0x80:
        return PAL_DV_FRAME_BYTES
    return NTSC_DV_FRAME_BYTES


def read_recording_datetime(frame: bytes | bytearray | memoryview) -> datetime | None:
    """Extract the camera recording date/time from one raw DV frame.

    Common DV camcorders write datecode as BCD date/time packs. In practice the
    most common source is VAUX 0x62/0x63; IEC/FFmpeg also define AAUX 0x52/0x53,
    and some tooling exposes video date packs in the subcode area. DV datecode
    has no reliable timezone, so we store it as UTC for stable filenames and
    filesystem mtimes on an appliance that otherwise runs in UTC.
    """

    if len(frame) < 4:
        return None
    frame_size = dv_frame_size(frame)
    if len(frame) < frame_size:
        return None

    for date_pack, time_pack in _recording_date_pack_pairs(frame):
        recorded_at = _read_datetime_from_packs(date_pack, time_pack)
        if recorded_at is not None:
            return recorded_at
    return None


def read_first_recording_datetime(path: str | os.PathLike[str], max_bytes: int = DEFAULT_SCAN_BYTES) -> datetime | None:
    """Scan the start of a raw DV file for the first camera recording date."""

    scanner = DvRecordingDateScanner()
    remaining = max_bytes
    try:
        with Path(path).open("rb") as handle:
            while remaining > 0:
                chunk = handle.read(min(128 * 1024, remaining))
                if not chunk:
                    return None
                remaining -= len(chunk)
                found = scanner.feed(chunk)
                if found is not None:
                    return found
    except OSError:
        return None
    return None


def stamp_file_from_dv_recording_date(path: str | os.PathLike[str], max_bytes: int = DEFAULT_SCAN_BYTES) -> datetime | None:
    """Best-effort: set a raw DV file mtime to its embedded recording date."""

    capture_path = Path(path)
    recorded_at = read_first_recording_datetime(capture_path, max_bytes=max_bytes)
    if recorded_at is None:
        return None
    try:
        current = capture_path.stat()
        os.utime(capture_path, (current.st_atime, recorded_at.timestamp()))
    except OSError:
        return None
    return recorded_at


class DvRecordingDateScanner:
    """Incrementally parse raw DV bytes from dvgrab stdout for datecode."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.latest: datetime | None = None

    def feed(self, chunk: bytes) -> datetime | None:
        if not chunk:
            return None
        self._buffer.extend(chunk)
        while len(self._buffer) >= 4:
            frame_size = dv_frame_size(self._buffer)
            if len(self._buffer) < frame_size:
                break
            frame = memoryview(self._buffer)[:frame_size]
            recorded_at = read_recording_datetime(frame)
            del frame
            del self._buffer[:frame_size]
            if recorded_at is not None:
                self.latest = recorded_at
                return recorded_at
        # Bound memory if the stream is malformed or starts mid-frame.
        if len(self._buffer) > PAL_DV_FRAME_BYTES * 2:
            del self._buffer[:-PAL_DV_FRAME_BYTES]
        return None


def _recording_date_pack_pairs(frame: bytes | bytearray | memoryview) -> list[tuple[bytes | None, bytes | None]]:
    """Return date/time pack pairs in most-common-first order."""

    return [
        # IEC/FFmpeg VAUX recording date/time: most consumer DV datecode lands here.
        (_find_vaux_pack(frame, DV_VIDEO_RECORD_DATE_PACK), _find_vaux_pack(frame, DV_VIDEO_RECORD_TIME_PACK)),
        # IEC/FFmpeg AAUX equivalents. Less commonly needed, but cheap to scan.
        (_find_aaux_pack(frame, DV_AUDIO_RECORD_DATE_PACK), _find_aaux_pack(frame, DV_AUDIO_RECORD_TIME_PACK)),
        # Subcode fallback for streams/tools that place/expose video date packs there.
        (_find_ssyb_pack(frame, DV_VIDEO_RECORD_DATE_PACK), _find_ssyb_pack(frame, DV_VIDEO_RECORD_TIME_PACK)),
    ]


def _read_datetime_from_packs(date_pack: bytes | None, time_pack: bytes | None) -> datetime | None:
    if date_pack is None or time_pack is None:
        return None

    day = _decode_bcd(date_pack[2], 0x3)
    month = _decode_bcd(date_pack[3], 0x1)
    year = _decode_bcd(date_pack[4], 0xF)
    second = _decode_bcd(time_pack[2], 0x7)
    minute = _decode_bcd(time_pack[3], 0x7)
    hour = _decode_bcd(time_pack[4], 0x3)
    if None in {day, month, year, second, minute, hour}:
        return None

    # Match current dvgrab: 00-94 => 2000-2094, 95-99 => 1995-1999.
    full_year = int(year) + (2000 if int(year) < 95 else 1900)
    try:
        return datetime(
            full_year,
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def _find_ssyb_pack(frame: bytes | bytearray | memoryview, pack_num: int) -> bytes | None:
    seq_count = 12 if dv_frame_size(frame) == PAL_DV_FRAME_BYTES else 10
    for sequence in range(seq_count):
        sequence_base = sequence * DIF_SEQUENCE_BYTES
        for block in range(2):
            block_base = sequence_base + 1 * 80 + block * 80
            for packet in range(6):
                offset = block_base + 3 + packet * 8 + 3
                if offset + 5 > len(frame):
                    continue
                if frame[offset] == pack_num:
                    return bytes(frame[offset : offset + 5])
    return None


def _find_aaux_pack(frame: bytes | bytearray | memoryview, pack_num: int) -> bytes | None:
    seq_count = 12 if dv_frame_size(frame) == PAL_DV_FRAME_BYTES else 10
    for sequence in range(seq_count):
        sequence_base = sequence * DIF_SEQUENCE_BYTES
        for block in range(9):
            offset = sequence_base + 6 * 80 + block * 16 * 80 + 3
            if offset + 5 > len(frame):
                continue
            if frame[offset] == pack_num:
                return bytes(frame[offset : offset + 5])
    return None


def _find_vaux_pack(frame: bytes | bytearray | memoryview, pack_num: int) -> bytes | None:
    seq_count = 12 if dv_frame_size(frame) == PAL_DV_FRAME_BYTES else 10
    for sequence in range(seq_count):
        sequence_base = sequence * DIF_SEQUENCE_BYTES
        for block in range(3):
            block_base = sequence_base + 3 * 80 + block * 80
            for packet in range(15):
                offset = block_base + 3 + packet * 5
                if offset + 5 > len(frame):
                    continue
                if frame[offset] == pack_num:
                    return bytes(frame[offset : offset + 5])
    return None


def _decode_bcd(value: int, tens_mask: int) -> int | None:
    ones = value & 0xF
    tens = (value >> 4) & tens_mask
    if ones > 9 or tens > 9:
        return None
    return ones + 10 * tens
