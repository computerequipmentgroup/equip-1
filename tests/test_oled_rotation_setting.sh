#!/usr/bin/env bash
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }

grep -q 'oled_rotate_180: bool = False' src/equip1d/models.py || fail "daemon state must expose oled_rotate_180"
grep -q 'set_oled_rotate_180' src/equip1d/service.py || fail "daemon service must persist oled rotation"
grep -q '/api/settings/oled-rotation' src/equip1d/api.py || fail "REST API must expose oled rotation setting"
grep -q 'oled_rotate_180 = false' src/buildroot/overlay/etc/equip1/equip-1.ini || fail "default INI must include oled_rotate_180"
grep -q 'img.rotate(180)' src/uis/oled/display.py || fail "OLED renderer must rotate framebuffer image"
grep -q 'OLED rotate' src/uis/oled/screens.py || fail "OLED settings screen must expose rotate toggle"
grep -q 'setOledRotate180' src/uis/web/composables/useEquip1State.ts || fail "web composable must expose rotation setter"
grep -q 'OLED rotation' src/uis/web/pages/index.vue || fail "web UI must expose display rotation toggle"

echo "ok - OLED rotation setting is wired through daemon, OLED, and web UI"
