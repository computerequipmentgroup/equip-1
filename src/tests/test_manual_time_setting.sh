#!/usr/bin/env bash
set -euo pipefail
root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$root"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

grep -q '@app.post("/api/time/manual")' src/equip1d/api.py || fail "daemon must expose manual time API"
grep -q 'def set_manual_time' src/equip1d/service.py || fail "daemon service must implement manual time setting"
grep -q 'local_epoch_seconds' src/equip1d/timezone.py || fail "timezone helper must convert local manual time to epoch seconds"
grep -q 'Set Date & Time' src/uis/web/pages/index.vue || fail "web System card must expose manual date/time controls"
grep -q 'type="date"' src/uis/web/pages/index.vue || fail "web time control must expose date input"
grep -q 'type="time"' src/uis/web/pages/index.vue || fail "web time control must expose hour/minute input"
grep -q '"/time/manual"' src/uis/oled/screens.py || fail "OLED Time screen must post manual time"

PYTHONPATH=src python3 - <<'PY' || fail "manual time parsing must accept date plus hour/minute and reject seconds-only/old years"
import calendar
from datetime import datetime
from equip1d.service import Equip1Daemon, CommandError
from equip1d.timezone import local_epoch_seconds

parsed = Equip1Daemon._parse_manual_time_payload({"date": "2026-09-29", "time": "14:07"})
assert parsed == datetime(2026, 9, 29, 14, 7)
parsed_iso = Equip1Daemon._parse_manual_time_payload({"local": "2026-09-29T14:07"})
assert parsed_iso == parsed
assert local_epoch_seconds("UTC", parsed) == calendar.timegm(parsed.timetuple())
try:
    Equip1Daemon._parse_manual_time_payload({"date": "2019-12-31", "time": "23:59"})
except CommandError:
    pass
else:
    raise AssertionError("old years must be rejected")
PY

echo "ok - manual time setting is wired"
