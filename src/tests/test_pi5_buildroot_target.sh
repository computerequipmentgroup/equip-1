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
grep -q 'set_ini_key board_type rpi' "$pi_post" || fail "Pi post-build must set rpi board type"
grep -q 'set_ini_key oled_fps 2' "$pi_post" || fail "Pi post-build must lower OLED FPS for shared I2C bus"
grep -q 'set_ini_key oled_settle_delay 15' "$pi_post" || fail "Pi post-build must delay OLED startup for PiSugar I2C settle"
grep -q 'set_ini_key oled_recover_max_delay 20.0' "$pi_post" || fail "Pi post-build must back off OLED I2C recovery on Pi 5"

# Pi 5 images use BusyBox modprobe, so kernel modules must be plain .ko files;
# compressed .ko.xz modules produced the observed invalid-ELF/rfkill boot error.
grep -q '^CONFIG_MODULE_COMPRESS_NONE=y$' src/buildroot/configs/linux-pi5.config || fail "Pi kernel modules must be uncompressed"
grep -q 'compressed kernel modules' "$build_script" || fail "build must reject compressed Pi kernel modules"
grep -q "name '\*.ko.xz'" "$build_script" || fail "build must scan for .ko.xz modules"

# PiSugar/OLED need /dev/i2c-1 on header pins 3/5; keep the compatible dtparam
# and verify the generated Pi boot config before publishing an image. Pi 5 header
# I2C is on the RP1 DesignWare controller, not only the older BCM controller.
grep -q '^dtparam=pciex1$' src/buildroot/configs/config_5_pisugar.txt || fail "Pi boot config must enable external PCIe"
grep -q '^dtparam=pciex1_gen=1$' src/buildroot/configs/config_5_pisugar.txt || fail "Pi test image must force external PCIe Gen 1 for signal-margin diagnosis"
grep -q '^dtparam=i2c_arm=on$' src/buildroot/configs/config_5_pisugar.txt || fail "Pi boot config must enable header I2C"
grep -q '^dtoverlay=i2c1-pi5' src/buildroot/configs/config_5_pisugar.txt || fail "Pi boot config should pin Pi 5 I2C1 overlay"
grep -q '^CONFIG_I2C_DESIGNWARE_PLATFORM=y$' src/buildroot/configs/linux-pi5.config || fail "Pi kernel must enable RP1 DesignWare I2C"
grep -q 'dtparam=i2c_arm=on' "$build_script" || fail "build must verify Pi I2C boot config"
grep -q 'CONFIG_I2C_DESIGNWARE_PLATFORM' "$build_script" || fail "build must verify Pi DesignWare I2C"

bash -n "$build_script"
bash -n "$pi_post"
sh -n "$network_script"

echo "ok - Pi 5 Buildroot target is isolated from Rock build leftovers"
