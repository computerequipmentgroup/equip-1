#!/usr/bin/env bash
# Raspberry Pi 5 post-build adjustments for the Equip-1 PiSugar image.
set -euo pipefail

TARGET_DIR="${TARGET_DIR:?}"

# Incremental Buildroot target trees can keep generated/stale scripts and Rock
# Wi-Fi payloads when switching targets. Remove them so the Pi image does not
# try to insert AIC8800 modules built for a different kernel.
rm -f "${TARGET_DIR}/etc/init.d/S40network"
find "${TARGET_DIR}/lib/modules" -type f \( -name 'aic_load_fw.ko' -o -name 'aic8800_fdrv.ko' \) -delete 2>/dev/null || true
rm -rf "${TARGET_DIR}/lib/firmware/aic8800_fw"

# Select the Raspberry Pi GPIO/I2C mapping at runtime. The same source tree also
# supports ROCK 2F, so this image flips only the generated target settings.
if [ -f "${TARGET_DIR}/etc/equip1/equip-1.ini" ]; then
    set_ini_key() {
        local key="$1"
        local value="$2"
        if grep -q "^${key}[[:space:]]*=" "${TARGET_DIR}/etc/equip1/equip-1.ini"; then
            sed -i "s/^${key}[[:space:]]*=.*/${key} = ${value}/" "${TARGET_DIR}/etc/equip1/equip-1.ini"
        elif grep -q '^\[ui\]' "${TARGET_DIR}/etc/equip1/equip-1.ini"; then
            sed -i "/^\[ui\]/a ${key} = ${value}" "${TARGET_DIR}/etc/equip1/equip-1.ini"
        fi
    }

    set_ini_key board_type rpi
    # The Pi 5/PiSugar stack brings up PiSugar RTC/battery I2C and the OLED on
    # the same bus. Give PiSugar time to settle and run the OLED at a lower
    # cadence on this recovery image to avoid hammering a marginal bus.
    set_ini_key oled_fps 2
    set_ini_key oled_settle_delay 15
    set_ini_key oled_recover_base_delay 2.0
    set_ini_key oled_recover_max_delay 20.0
fi

# The Pi 5 image carries the PiSugar server binary in the overlay. Make startup
# scripts executable even if the host filesystem lost mode bits.
chmod +x \
    "${TARGET_DIR}/etc/init.d/S55pisugar-server" \
    "${TARGET_DIR}/etc/init.d/S60equip1d" \
    "${TARGET_DIR}/etc/init.d/S61equip1-oled" \
    2>/dev/null || true

# Sanity checks for the PiSugar payload.
if [ ! -x "${TARGET_DIR}/usr/bin/pisugar-server" ]; then
    echo "ERROR: PiSugar image is missing /usr/bin/pisugar-server"
    exit 1
fi
if [ ! -f "${TARGET_DIR}/etc/pisugar-server/config.json" ]; then
    echo "ERROR: PiSugar image is missing /etc/pisugar-server/config.json"
    exit 1
fi

echo "==> Pi 5 post-build OK: board_type=rpi, PiSugar server staged, Rock Wi-Fi payloads removed."
