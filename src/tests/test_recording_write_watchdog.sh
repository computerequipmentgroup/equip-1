#!/usr/bin/env bash
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }

root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$root"

PYTHONPATH=src python3 - <<'PY' || fail "recording watchdog must fail silent non-writes"
import os
import tempfile
import time

# Read by DvSource.__init__.
os.environ["EQUIP1_RECORDING_FIRST_BYTES_TIMEOUT"] = "0"
os.environ["EQUIP1_RECORDING_STALL_TIMEOUT"] = "999"

from equip1d.dvsource import DvSource
from equip1d.recorder import RecordingTracker

with tempfile.TemporaryDirectory() as tmp:
    source = DvSource()
    tracker = RecordingTracker(tmp, source)
    state = tracker.start(filename_stem="capture_watchdog", extension="dv")
    assert state.active is True
    rc = tracker.poll()
    assert rc == 1, rc
    assert tracker.state.active is False
    assert source.recording is False
    assert source.recording_error is not None
    assert "No DV/HDV bytes reached the recording writer" in source.recording_error, source.recording_error

# A write that reaches the sink must satisfy the first-byte watchdog.
os.environ["EQUIP1_RECORDING_FIRST_BYTES_TIMEOUT"] = "999"
os.environ["EQUIP1_RECORDING_STALL_TIMEOUT"] = "999"
with tempfile.TemporaryDirectory() as tmp:
    source = DvSource()
    tracker = RecordingTracker(tmp, source)
    tracker.start(filename_stem="capture_ok", extension="dv")
    assert source._rec_queue is not None
    source._rec_queue.put(b"dv-bytes")
    deadline = time.monotonic() + 2
    while source.recording_stats()["bytes_written"] == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert source.recording_stats()["bytes_written"] == len(b"dv-bytes"), source.recording_stats()
    assert tracker.poll() is None
    tracker.stop()

# Bytes accepted by the writer are not enough: the visible capture file must
# also appear/grow. This catches muxer/output failures where the UI timer could
# otherwise keep running even though no usable file is being committed.
os.environ["EQUIP1_RECORDING_FIRST_BYTES_TIMEOUT"] = "0"
os.environ["EQUIP1_RECORDING_STALL_TIMEOUT"] = "999"
with tempfile.TemporaryDirectory() as tmp:
    source = DvSource()
    tracker = RecordingTracker(tmp, source)
    state = tracker.start(filename_stem="capture_missing_file", extension="dv")
    assert state.filename is not None
    visible_path = os.path.join(tmp, state.filename)
    os.unlink(visible_path)
    assert source._rec_queue is not None
    source._rec_queue.put(b"dv-bytes")
    deadline = time.monotonic() + 2
    while source.recording_stats()["bytes_written"] == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert source.recording_stats()["bytes_written"] == len(b"dv-bytes"), source.recording_stats()
    rc = tracker.poll()
    assert rc == 1, rc
    assert "Recording file did not grow" in (source.recording_error or ""), source.recording_error
PY

grep -q 'recording_health_error' src/equip1d/recorder.py || fail "tracker must poll source recording health"
grep -q 'No DV/HDV bytes reached the recording writer' src/equip1d/dvsource.py || fail "DV source must have first-byte watchdog error"
grep -q 'Recording failed' src/equip1d/service.py || fail "daemon state must expose watchdog failures as recording errors"

echo "ok - recording watchdog catches silent non-writes"
