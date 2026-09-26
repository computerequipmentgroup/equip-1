#!/usr/bin/env bash
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }

root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$root"

grep -q 'oled_fps = settings.get_float("ui", "oled_fps", 8.0' src/uis/oled/app.py || fail "OLED app default FPS must be 8"
grep -q 'equip1_ini_default EQUIP1_OLED_FPS ui oled_fps 8' src/buildroot/overlay/etc/init.d/S61equip1-oled || fail "OLED init script INI default must be 8 FPS"
grep -q 'export EQUIP1_OLED_FPS="${EQUIP1_OLED_FPS:-8}"' src/buildroot/overlay/etc/init.d/S61equip1-oled || fail "OLED init script fallback must be 8 FPS"
grep -q 'oled_fps = 8' src/buildroot/overlay/etc/equip1/equip-1.ini || fail "shipped INI must set 8 FPS"
grep -q '_state_for_render' src/uis/oled/app.py || fail "OLED app must synthesize render state"
grep -q 'OLED display reinitialized after I2C error' src/uis/oled/display.py || fail "OLED display must recover from transient I2C errors"
grep -q 'OLED display reinit failed: .*backing off' src/uis/oled/display.py || fail "OLED display recovery must back off after repeated I2C failures"
grep -q 'equip1_ini_default EQUIP1_OLED_SETTLE_DELAY ui oled_settle_delay 0' src/buildroot/overlay/etc/init.d/S61equip1-oled || fail "OLED init script must expose settle delay"
grep -q 'equip1_ini_default EQUIP1_OLED_RECOVER_BASE_DELAY ui oled_recover_base_delay 1.0' src/buildroot/overlay/etc/init.d/S61equip1-oled || fail "OLED init script must expose recovery base delay"

PYTHONPATH=src python3 - <<'PY'
import time
from uis.oled.app import OledApp

app = object.__new__(OledApp)
app.state = {
    "mode": "recording",
    "recording": {"active": True, "elapsed_seconds": 10},
}
app._recording_elapsed_base_seconds = 10
app._recording_elapsed_base_at = time.monotonic() - 2.2

render_state = app._state_for_render({"mode": "offline"})
if render_state["recording"]["elapsed_seconds"] != 12:
    raise SystemExit(f"expected locally estimated elapsed=12, got {render_state['recording']['elapsed_seconds']}")
if app.state["recording"]["elapsed_seconds"] != 10:
    raise SystemExit("render-time elapsed estimation must not mutate cached API state")

app.state = {"mode": "idle", "recording": {"elapsed_seconds": 10}}
if app._state_for_render({"mode": "offline"}) is not app.state:
    raise SystemExit("non-recording state should pass through unchanged")
PY

echo "ok - OLED timing defaults and elapsed display are stable"
