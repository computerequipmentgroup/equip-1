from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

NTSC_DV_FRAME_BYTES = 120_000
PAL_DV_FRAME_BYTES = 144_000
DIF_SEQUENCE_BYTES = 150 * 80
DV_AUDIO_RECORD_DATE_PACK = 0x52
DV_AUDIO_RECORD_TIME_PACK = 0x53
DV_SUBCODE_TIMECODE_PACK = 0x13
DV_VIDEO_RECORD_DATE_PACK = 0x62
DV_VIDEO_RECORD_TIME_PACK = 0x63
DEFAULT_SCAN_BYTES = PAL_DV_FRAME_BYTES * 20


@dataclass(frozen=True)
class DvTimecode:
    hour: int
    minute: int
    second: int
    frame: int
    drop_frame: bool = False

    def __str__(self) -> str:
        separator = ";" if self.drop_frame else ":"
        return f"{self.hour:02d}:{self.minute:02d}:{self.second:02d}{separator}{self.frame:02d}"


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


def read_timecode(frame: bytes | bytearray | memoryview) -> DvTimecode | None:
    """Extract SMPTE-style tape/program timecode from one raw DV frame.

    DV timecode is a subcode SSYB pack (0x13) stored as BCD hour/minute/second
    plus frame number. Unlike datecode, this is a media position such as
    ``00:12:43:08``; it is not a wall-clock timestamp.
    """

    if len(frame) < 4:
        return None
    frame_size = dv_frame_size(frame)
    if len(frame) < frame_size:
        return None

    pack = _find_ssyb_pack(frame, DV_SUBCODE_TIMECODE_PACK)
    if pack is None:
        return None

    frame_number = _decode_bcd(pack[1], 0x3)
    second = _decode_bcd(pack[2], 0x7)
    minute = _decode_bcd(pack[3], 0x7)
    hour = _decode_bcd(pack[4], 0x3)
    if None in {frame_number, second, minute, hour}:
        return None

    frame_limit = 25 if frame_size == PAL_DV_FRAME_BYTES else 30
    if int(hour) > 23 or int(minute) > 59 or int(second) > 59 or int(frame_number) >= frame_limit:
        return None

    return DvTimecode(
        hour=int(hour),
        minute=int(minute),
        second=int(second),
        frame=int(frame_number),
        drop_frame=bool(pack[1] & 0x40),
    )


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
        found = _feed_raw_dv_frames(self._buffer, chunk, read_recording_datetime)
        if found is not None:
            self.latest = found
        return found


class DvTimecodeScanner:
    """Incrementally parse raw DV bytes from dvgrab stdout for timecode."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.latest: DvTimecode | None = None

    def feed(self, chunk: bytes) -> DvTimecode | None:
        found = _feed_raw_dv_frames(self._buffer, chunk, read_timecode)
        if found is not None:
            self.latest = found
        return found


def _feed_raw_dv_frames(buffer: bytearray, chunk: bytes, reader):
    if not chunk:
        return None
    buffer.extend(chunk)
    latest = None
    while len(buffer) >= 4:
        frame_size = dv_frame_size(buffer)
        if len(buffer) < frame_size:
            break
        frame = memoryview(buffer)[:frame_size]
        found = reader(frame)
        del frame
        del buffer[:frame_size]
        if found is not None:
            latest = found
    # Bound memory if the stream is malformed or starts mid-frame.
    if len(buffer) > PAL_DV_FRAME_BYTES * 2:
        del buffer[:-PAL_DV_FRAME_BYTES]
    return latest


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
