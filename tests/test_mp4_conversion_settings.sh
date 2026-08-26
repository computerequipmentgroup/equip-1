#!/usr/bin/env bash
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }

grep -q 'AUTO_CONVERT_MP4_DEFAULT = False' src/equip1d/settings.py || fail "auto MP4 conversion must be off by default in code"
grep -q 'auto_convert_mp4 = false' src/buildroot/overlay/etc/equip1/equip-1.ini || fail "default INI must disable auto MP4 conversion"
grep -q 'convert_all_captures_to_mp4' src/equip1d/service.py || fail "daemon service must expose convert-all operation"
grep -q '/api/commands/convert-all-mp4' src/equip1d/api.py || fail "REST API must expose convert-all command"
grep -q 'CONVERT all' src/uis/oled/screens.py || fail "OLED settings must include CONVERT all option"
grep -q "runCommand('convert-all-mp4')" src/uis/web/pages/index.vue || fail "web settings must expose Convert all command"
grep -q 'setConversionSettings' src/uis/web/composables/useEquip1State.ts || fail "web composable must expose conversion settings setter"
grep -q 'MP4 export' src/uis/web/pages/index.vue || fail "web UI must expose MP4 export toggle"
grep -q 'Deinterlace' src/uis/web/pages/index.vue || fail "web UI must expose MP4 deinterlace toggle"

echo "ok - MP4 conversion defaults and Convert all setting are wired"
