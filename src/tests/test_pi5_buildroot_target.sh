#!/bin/sh
set -eu
fail() { echo "FAIL: $*" >&2; exit 1; }

root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$root"

build_script=src/buildroot/scripts/build.sh
pi_post=src/buildroot/scripts/post-build-pi5.sh
network_script=src/buildroot/overlay/etc/init.d/S50network

# Pi builds must use the Pi kernel fragment, not a stale Rock linux.config from
# a reused Buildroot VM tree.
grep -q 'KERNEL_CONFIG_FRAGMENT="linux-pi5.config"' "$build_script" || fail "Pi target must select linux-pi5.config"
grep -q 'KERNEL_CONFIG_FRAGMENT="linux.config"' "$build_script" || fail "Rock target must select linux.config"
grep -q 'BR2_LINUX_KERNEL_CONFIG_FRAGMENT_FILES=.*$KERNEL_CONFIG_FRAGMENT' "$build_script" || fail "build must patch Buildroot to use the selected kernel fragment"
! grep -q 'BR2_LINUX_KERNEL_CONFIG_FRAGMENT_FILES=.*linux.config' "$build_script" || fail "build must not hard-code linux.config for every board"

# Reusing one Buildroot output directory across boards leaves stale kernel
# modules and image files in output/target. The build must clean unmarked or
# wrong-board output before continuing.
grep -q 'BOARD_STAMP="output/.equip1-target-board"' "$build_script" || fail "build must stamp the output tree board"
grep -q 'cleaning once to avoid cross-board leftovers' "$build_script" || fail "build must clean legacy unmarked output"
grep -q 'cleaning for $TARGET_BOARD' "$build_script" || fail "build must clean output when switching boards"

# Pi images must not try to load Radxa AIC8800 modules. The runtime script should
# load Broadcom Wi-Fi normally, and post-build should scrub stale Rock payloads.
grep -q 'EQUIP_1_BOARD_TYPE ui board_type rock2f' "$network_script" || fail "network init must read board_type"
grep -q 'modprobe brcmfmac' "$network_script" || fail "Pi network init should use Broadcom Wi-Fi autoload"
grep -q 'aic_load_fw.ko' "$pi_post" || fail "Pi post-build must delete stale AIC load module"
grep -q 'aic8800_fdrv.ko' "$pi_post" || fail "Pi post-build must delete stale AIC WLAN module"
grep -q 'lib/firmware/aic8800_fw' "$pi_post" || fail "Pi post-build must delete stale AIC firmware"

bash -n "$build_script"
bash -n "$pi_post"
sh -n "$network_script"

echo "ok - Pi 5 Buildroot target is isolated from Rock build leftovers"
