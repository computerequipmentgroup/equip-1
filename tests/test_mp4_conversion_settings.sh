#!/usr/bin/env bash
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }

grep -q 'AUTO_CONVERT_MP4_DEFAULT = True' src/equip1d/settings.py || fail "auto MP4 conversion must default on in code"
grep -q 'AUTO_CONVERT_MP4_MODE_DEFAULT = "background"' src/equip1d/settings.py || fail "auto MP4 conversion must default to background mode"
grep -q 'MP4_DEINTERLACE_DEFAULT = False' src/equip1d/settings.py || fail "MP4 deinterlace must default off in code"
grep -q 'AUTO_CONVERT_MP4_MODE_OPTIONS = ("off", "foreground", "background")' src/equip1d/settings.py || fail "auto MP4 conversion must support off/foreground/background modes"
grep -q 'auto_convert_mp4 = true' src/buildroot/overlay/etc/equip1/equip-1.ini || fail "default INI must enable auto MP4 conversion"
grep -q 'auto_convert_mp4_mode = background' src/buildroot/overlay/etc/equip1/equip-1.ini || fail "default INI must set auto MP4 mode background"
grep -q 'mp4_deinterlace = false' src/buildroot/overlay/etc/equip1/equip-1.ini || fail "default INI must disable MP4 deinterlace"
grep -q 'convert_all_captures_to_mp4' src/equip1d/service.py || fail "daemon service must expose convert-all operation"
grep -q '/api/commands/convert-all-mp4' src/equip1d/api.py || fail "REST API must expose convert-all command"
if grep -q 'CONVERT all' src/uis/oled/screens.py; then
  fail "OLED settings must not expose Convert all"
fi
if grep -q "runCommand('convert-all-mp4')" src/uis/web/pages/index.vue; then
  fail "web UI must not expose Convert all command"
fi
grep -q 'setConversionSettings' src/uis/web/composables/useEquip1State.ts || fail "web composable must expose conversion settings setter"
grep -q 'mp4_deinterlace_algorithm' src/equip1d/models.py || fail "daemon state must expose deinterlace algorithm"
grep -q '_configured_deinterlace_algorithm' src/equip1d/service.py || fail "daemon service must report configured deinterlace algorithm"
grep -q 'BR2_PACKAGE_FFMPEG_GPL=y' src/buildroot/configs/equip1_defconfig || fail "Rock ffmpeg must enable GPL filters for NNEDI deinterlacing"
grep -q -- '--disable-gpl' src/buildroot/scripts/build.sh || fail "build script must force ffmpeg rebuild when GPL filters were previously disabled"
grep -q 'MP4 Conversion' src/uis/web/pages/index.vue || fail "web UI must expose MP4 conversion toggle"
grep -q 'mp4ConversionModeLabel' src/uis/web/pages/index.vue || fail "web UI must label MP4 conversion mode"
grep -q 'tri-switch' src/uis/web/pages/index.vue || fail "web UI must render a three-state MP4 conversion control"
grep -q 'auto_mp4_mode' src/uis/web/composables/useEquip1State.ts || fail "web composable must send MP4 conversion mode"
grep -q 'auto_mp4_mode' src/equip1d/models.py || fail "daemon state must expose MP4 conversion mode"
grep -q '_conversion_blocks_recording' src/equip1d/service.py || fail "daemon service must track whether conversion blocks recording"
grep -q 'mp4DeinterlaceAlgorithmLabel' src/uis/web/pages/index.vue || fail "web UI must render dynamic MP4 deinterlace algorithm label"
grep -q 'conversionActive' src/uis/web/app.vue || fail "web header must account for active background conversion"
grep -q "if (conversionActive.value) return 'Busy'" src/uis/web/app.vue || fail "web header must show Busy during conversion"
grep -q '_last_conversion_progress_publish' src/equip1d/service.py || fail "daemon must publish conversion progress updates"

echo "ok - MP4 conversion defaults and web settings are wired"
