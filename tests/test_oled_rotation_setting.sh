#!/usr/bin/env bash
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }

grep -q 'oled_rotate_180: bool = False' src/equip1d/models.py || fail "daemon state must expose oled_rotate_180"
grep -q 'set_oled_rotate_180' src/equip1d/service.py || fail "daemon service must persist oled rotation"
grep -q '/api/settings/oled-rotation' src/equip1d/api.py || fail "REST API must expose oled rotation setting"
grep -q 'oled_rotate_180 = false' src/buildroot/overlay/etc/equip1/equip-1.ini || fail "default INI must include oled_rotate_180"
grep -q 'img.rotate(180)' src/uis/oled/display.py || fail "OLED renderer must rotate framebuffer image"
grep -q '_oled_rotate_180_enabled' src/uis/oled/app.py || fail "OLED app must read rotation state for input mapping"
grep -q 'logical_up = events.up' src/uis/oled/app.py || fail "OLED app must flip up/down buttons when rotated"
grep -q 'logical_up = name == "up" if rotate_180 else name == "down"' src/uis/oled/designer.py || fail "OLED designer must simulate rotated button mapping"
grep -q 'OLED flip' src/uis/oled/screens.py || fail "OLED settings screen must expose flip toggle"
grep -q 'setOledRotate180' src/uis/web/composables/useEquip1State.ts || fail "web composable must expose rotation setter"
grep -q 'Flip Display: {{ oledFlipLabel }}' src/uis/web/pages/index.vue || fail "web UI must expose display flip orientation label"
grep -q "'BR'" src/uis/oled/screens.py || fail "OLED flip off state must use two-character buttons-right label"
grep -q "'BL'" src/uis/oled/screens.py || fail "OLED flip on state must use two-character buttons-left label"
PYTHONPATH=src python3 - <<'PY'
import re
from uis.oled.screens import SettingsScreen

screen = SettingsScreen()
state = {
    "conversion": {"auto_mp4_mode": "foreground", "mp4_deinterlace_enabled": False, "active": True},
    "settings": {"recording_format": "mov", "auto_storage_switch": False, "hdmi_preview_enabled": True, "oled_rotate_180": True},
    "lights": {"enabled": False},
}
for index in range(8):
    label = screen._option_label(state, index)
    match = re.search(r"\[([^\]]+)\]", label)
    if match and len(match.group(1)) > 3:
        raise SystemExit(f"OLED bracket label is too long: {label}")
required = {"LEDs [OFF]", "OLED flip [BL]", "FORMAT [MOV]", "MP4 export [FG]", "MP4 deint [OFF]"}
labels = {screen._option_label(state, index) for index in range(8)}
missing = required - labels
if missing:
    raise SystemExit(f"missing expected OLED labels: {sorted(missing)}")
PY

echo "ok - OLED display flip setting is wired through daemon, OLED, and web UI"
