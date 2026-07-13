from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from equip1d.dvmetadata import DvRecordingDateScanner, read_recording_datetime, stamp_file_from_dv_recording_date


def bcd(value: int) -> int:
    return ((value // 10) << 4) | (value % 10)


def put_ssyb_pack(frame: bytearray, pack: bytes, *, sequence: int = 0, block: int = 0, packet: int = 0) -> None:
    offset = sequence * 150 * 80 + 1 * 80 + block * 80 + 3 + packet * 8 + 3
    frame[offset : offset + len(pack)] = pack


def put_vaux_pack(frame: bytearray, pack: bytes, *, sequence: int = 0, block: int = 0, packet: int = 0) -> None:
    offset = sequence * 150 * 80 + 3 * 80 + block * 80 + 3 + packet * 5
    frame[offset : offset + len(pack)] = pack


def put_aaux_pack(frame: bytearray, pack: bytes, *, sequence: int = 0, block: int = 0) -> None:
    offset = sequence * 150 * 80 + 6 * 80 + block * 16 * 80 + 3
    frame[offset : offset + len(pack)] = pack


def make_ntsc_ssyb_frame(dt: datetime) -> bytes:
    frame = bytearray(120_000)
    frame[3] = 0x00  # DSF clear => NTSC frame size.
    put_ssyb_pack(frame, bytes([0x62, 0xFF, bcd(dt.day), bcd(dt.month), bcd(dt.year % 100)]), packet=0)
    put_ssyb_pack(frame, bytes([0x63, 0xFF, bcd(dt.second), bcd(dt.minute), bcd(dt.hour)]), packet=1)
    return bytes(frame)


def make_ntsc_aaux_frame(dt: datetime) -> bytes:
    frame = bytearray(120_000)
    frame[3] = 0x00  # DSF clear => NTSC frame size.
    put_aaux_pack(frame, bytes([0x52, 0xFF, bcd(dt.day), bcd(dt.month), bcd(dt.year % 100)]), block=0)
    put_aaux_pack(frame, bytes([0x53, 0xFF, bcd(dt.second), bcd(dt.minute), bcd(dt.hour)]), block=1)
    return bytes(frame)


def make_pal_vaux_frame() -> bytes:
    frame = bytearray(144_000)
    frame[3] = 0x80  # DSF set => PAL frame size.
    # Real PAL VAUX datecode layout observed from the ROCK 2F SD capture:
    # 62 41 d3 e7 26 => 2026-07-13, 63 ff 98 93 d1 => 11:13:18.
    # Upper BCD nibbles carry flags, so the parser must mask them like dvgrab.
    put_vaux_pack(frame, bytes.fromhex("62 41 d3 e7 26"), packet=43)
    put_vaux_pack(frame, bytes.fromhex("63 ff 98 93 d1"), packet=44)
    return bytes(frame)


class DvRecordingDateTests(unittest.TestCase):
    def test_reads_recording_datetime_from_subcode_fallback(self):
        frame = make_ntsc_ssyb_frame(datetime(2026, 7, 13, 14, 5, 9, tzinfo=timezone.utc))

        self.assertEqual(read_recording_datetime(frame), datetime(2026, 7, 13, 14, 5, 9, tzinfo=timezone.utc))

    def test_reads_recording_datetime_from_pal_vaux_datecode(self):
        self.assertEqual(read_recording_datetime(make_pal_vaux_frame()), datetime(2026, 7, 13, 11, 13, 18, tzinfo=timezone.utc))

    def test_reads_recording_datetime_from_aaux_datecode(self):
        frame = make_ntsc_aaux_frame(datetime(2025, 2, 3, 4, 5, 6, tzinfo=timezone.utc))

        self.assertEqual(read_recording_datetime(frame), datetime(2025, 2, 3, 4, 5, 6, tzinfo=timezone.utc))

    def test_scanner_handles_frames_split_across_pipe_chunks(self):
        frame = make_ntsc_ssyb_frame(datetime(1999, 12, 31, 23, 59, 58, tzinfo=timezone.utc))
        scanner = DvRecordingDateScanner()

        self.assertIsNone(scanner.feed(frame[:80_000]))
        self.assertEqual(scanner.feed(frame[80_000:]), datetime(1999, 12, 31, 23, 59, 58, tzinfo=timezone.utc))
        self.assertEqual(scanner.latest, datetime(1999, 12, 31, 23, 59, 58, tzinfo=timezone.utc))

    def test_stamps_file_from_first_dv_recording_date(self):
        frame = make_ntsc_ssyb_frame(datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = Path(handle.name)
            handle.write(frame)
        try:
            stamped = stamp_file_from_dv_recording_date(path)

            self.assertEqual(stamped, datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
            self.assertEqual(round(os.stat(path).st_mtime), int(stamped.timestamp()))
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
