#!/bin/sh
set -eu

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

grep -q '/api/captures/{capture_name}/watch' src/equip1d/api.py || fail "REST API must expose capture watch endpoint"
grep -q '/api/captures/{capture_name}/conversion' src/equip1d/api.py || fail "REST API must expose single conversion endpoint"
grep -q '/api/captures/{capture_name}/sidecar' src/equip1d/api.py || fail "REST API must keep sidecar endpoint compatibility"
grep -q 'async def delete_capture' src/equip1d/api.py || fail "REST API must expose capture deletion endpoint"
grep -q 'convert_capture_to_mp4' src/equip1d/service.py || fail "daemon service must expose single conversion"
grep -q 'delete_capture' src/equip1d/storage.py || fail "storage manager must delete capture files"
grep -q 'duration_seconds' src/equip1d/storage.py || fail "backend capture list must expose duration metadata"
grep -q 'watch_url' src/equip1d/storage.py || fail "backend capture list must expose watch URLs"
grep -q 'thumbnail_url' src/equip1d/storage.py || fail "backend capture list must expose thumbnail URLs"
grep -q 'groupedCaptures' src/uis/web/pages/index.vue || fail "web UI must group conversions under primary captures"
grep -q 'captureThumbnailUrl' src/uis/web/pages/index.vue || fail "web UI must render capture thumbnail images"
grep -q 'const capturePageSize = 6' src/uis/web/pages/index.vue || fail "web UI must paginate captures at six entries per page"
grep -q 'paginatedCaptures' src/uis/web/pages/index.vue || fail "web UI must render paginated captures"
grep -q 'captureRecordingResyncMs = 1000' src/uis/web/composables/useEquip1State.ts || fail "web UI must poll captures every second while recording"
grep -q 'captureIdleResyncMs = 10000' src/uis/web/composables/useEquip1State.ts || fail "web UI must keep slower idle capture polling"
grep -q 'captureConversionStatus' src/uis/web/pages/index.vue || fail "captures list must show conversion status/progress"
grep -q 'Converting.*conversionProgressPercent' src/uis/web/pages/index.vue || fail "capture conversion action must show progress while converting"
grep -q 'i <= 27' src/uis/web/composables/useEquip1State.ts || fail "mock mode must include 27 capture groups for pagination testing"
grep -q 'capture-menu' src/uis/web/pages/index.vue || fail "web UI must render a full-width capture submenu"
grep -q 'Watch preview' src/uis/web/pages/index.vue || fail "web UI must expose watch preview action"
grep -q 'Close preview' src/uis/web/pages/index.vue || fail "web UI must expose close preview action"
grep -q 'Preparing preview' src/uis/web/pages/index.vue || fail "web UI must show conversion-before-watch feedback"
grep -q 'ensureWatchTarget' src/uis/web/pages/index.vue || fail "web UI must prepare an MP4 before playing captures"
grep -q 'Create conversion' src/uis/web/pages/index.vue || fail "web UI must expose conversion creation action"
grep -q '/conversion' src/uis/web/composables/useEquip1State.ts || fail "web composable must call conversion endpoint"
grep -q '_is_temporary_capture_path' src/equip1d/storage.py || fail "backend capture listing must filter conversion temp files"
python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory

from src.equip1d.storage import StorageManager

with TemporaryDirectory() as tmp:
    capture_dir = Path(tmp)
    (capture_dir / "capture_001.mov").write_bytes(b"ok")
    (capture_dir / "capture_001.tmp.mp4").write_bytes(b"tmp")
    storage = StorageManager(capture_dir)
    names = [row["name"] for row in storage.list_captures()]
    if names != ["capture_001.mov"]:
        raise SystemExit(f"temporary conversion leaked into captures: {names}")
    if storage.capture_path("capture_001.tmp.mp4") is not None:
        raise SystemExit("temporary conversion resolved as a playable capture")
PY
if grep -q 'Download conversion' src/uis/web/pages/index.vue; then
  fail "web UI must not expose a separate conversion download action"
fi

echo "ok - capture submenu actions are wired"
