#!/usr/bin/env bash
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }

root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$root"

PYTHONPATH=src python3 - <<'PY' || fail "HDV stream detection must tolerate short first reads"
from equip1d.dvsource import DvSource, STREAM_FORMAT_HDV, STREAM_FORMAT_UNKNOWN

class Loop:
    def call_soon_threadsafe(self, callback, *args):
        callback(*args)

def ts_packet(payload_byte: int = 0) -> bytes:
    payload = bytearray([payload_byte] * 187)
    # These offsets look like non-standard DV DIF headers. If an HDV stream is
    # misclassified as DV, the DIF normalizer will rewrite them and corrupt TS.
    payload[79] = 0x10
    payload[159] = 0x30
    return bytes([0x47]) + bytes(payload)

source = DvSource()
loop = Loop()
first = ts_packet(0x20)[:188]
prepared_first = source._prepare_chunk(first, loop)
assert source.stream_format == STREAM_FORMAT_UNKNOWN, source.stream_format
assert prepared_first == b""

second = ts_packet(0x21) + ts_packet(0x22) + ts_packet(0x23)
prepared_second = source._prepare_chunk(second, loop)
assert source.stream_format == STREAM_FORMAT_HDV, source.stream_format
assert prepared_second == first + second
PY

PYTHONPATH=src python3 - <<'PY' || fail "HDV preview must use MPEG-TS input"
from equip1d.dvsource import DvSource, STREAM_FORMAT_HDV
from equip1d.preview import MjpegPreview

source = DvSource()
source._stream_format = STREAM_FORMAT_HDV
command = MjpegPreview(source)._ffmpeg_stdin_command(stream_format=source.stream_format)
assert "-f" in command, command
assert command[command.index("-f") + 1] == "mpegts", command
PY

grep -q 'Could not determine DV/HDV stream format' src/equip1d/service.py || \
  fail "recording/preview should not fall back to DV while stream format is unknown"

echo "ok - HDV stream detection handles short first reads"
