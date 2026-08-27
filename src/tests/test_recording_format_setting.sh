#!/usr/bin/env bash
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }

root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$root"

grep -q 'RECORDING_FORMAT_DEFAULT = "mov"' src/equip1d/settings.py || fail "recording format must default to mov"
grep -q 'recording_format = mov' src/buildroot/overlay/etc/equip1/equip-1.ini || fail "default INI must set recording_format mov"
grep -q 'set_recording_format' src/equip1d/service.py || fail "daemon service must persist recording format"
grep -q '/api/settings/recording-format' src/equip1d/api.py || fail "REST API must expose recording format setting"
grep -q 'FORMAT' src/uis/oled/screens.py || fail "OLED settings must expose recording format"
grep -q 'setRecordingFormat' src/uis/web/composables/useEquip1State.ts || fail "web composable must expose recording format setter"
grep -q '>Format<' src/uis/web/pages/index.vue || fail "web UI must expose format setting"
grep -q 'const recordingFormatOptions = \["dv", "mov", "avi"\]' src/uis/web/pages/index.vue || fail "web UI must list DV first while keeping MOV default"
grep -q 'ffmpeg recording muxer' src/equip1d/dvsource.py || fail "DV source must support ffmpeg muxed MOV/AVI recordings"

echo "ok - recording format defaults and settings are wired"
