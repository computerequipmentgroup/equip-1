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
    if grep -q '^board_type[[:space:]]*=' "${TARGET_DIR}/etc/equip1/equip-1.ini"; then
        sed -i 's/^board_type[[:space:]]*=.*/board_type = rpi/' "${TARGET_DIR}/etc/equip1/equip-1.ini"
    elif grep -q '^\[ui\]' "${TARGET_DIR}/etc/equip1/equip-1.ini"; then
        sed -i '/^\[ui\]/a board_type = rpi' "${TARGET_DIR}/etc/equip1/equip-1.ini"
    fi
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
