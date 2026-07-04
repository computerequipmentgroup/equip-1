#!/usr/bin/env bash
# Post-build script run by buildroot after target filesystem is assembled
# but before post-image scripts (genimage). Runs inside the VM.
set -euo pipefail

IMAGES_DIR="${BINARIES_DIR}"
TARGET_DIR="${TARGET_DIR:?}"
BUILD_DIR="${BUILD_DIR:?}"
HOST_DIR="${HOST_DIR:?}"
AIC8800_REPO="${HOME}/aic8800"

apply_patch_once() {
    local repo="$1"
    local patchfile="$2"

    if patch -d "$repo" -p1 -N --dry-run < "$patchfile" >/dev/null 2>&1; then
        patch -d "$repo" -p1 -N < "$patchfile"
    elif patch -d "$repo" -p1 -R --dry-run < "$patchfile" >/dev/null 2>&1; then
        echo "==> AIC patch already applied: $(basename "$patchfile")"
    else
        echo "ERROR: Could not apply AIC patch $(basename "$patchfile")"
        return 1
    fi
}

ensure_aic8800_repo() {
    # Restore the cached checkout to a pristine state, or re-clone if it's missing or
    # corrupt. An unclean VM stop can leave a truncated git index and 0-byte source
    # files (e.g. empty Makefiles) -> `make modules` fails with "No rule to make
    # target 'modules'". The reset/clean is guarded so a corrupt index falls back to
    # a fresh clone instead of aborting the build (post-build runs under `set -e`).
    if [ -d "${AIC8800_REPO}/.git" ] \
        && git -C "${AIC8800_REPO}" reset --hard >/dev/null 2>&1 \
        && git -C "${AIC8800_REPO}" clean -fdx >/dev/null 2>&1; then
        echo "==> Restored cached AIC8800 driver repo to pristine state."
    else
        echo "==> AIC8800 repo missing/corrupt; cloning fresh..."
        rm -rf "${AIC8800_REPO}"
        git clone --depth 1 https://github.com/radxa-pkg/aic8800.git "${AIC8800_REPO}"
    fi

    apply_patch_once "${AIC8800_REPO}" "${AIC8800_REPO}/debian/patches/fix-linux-6.1-build.patch"
    apply_patch_once "${AIC8800_REPO}" "${AIC8800_REPO}/debian/patches/fix-usb-build.patch"
}

build_and_stage_aic8800() {
    local kernel_dir
    local kernel_release
    local driver_dir
    local mod_dest
    local firmware_dest
    local cross_compile

    kernel_dir="$(find "${BUILD_DIR}" -maxdepth 1 -type d -name 'linux-*' ! -name 'linux-headers-*' | head -1)"
    if [ -z "${kernel_dir}" ]; then
        echo "ERROR: Could not find built kernel tree under ${BUILD_DIR}"
        return 1
    fi
    if [ ! -f "${kernel_dir}/include/config/auto.conf" ]; then
        echo "ERROR: Kernel tree ${kernel_dir} is missing include/config/auto.conf"
        return 1
    fi

    driver_dir="${AIC8800_REPO}/src/USB/driver_fw/drivers/aic8800"
    cross_compile="${HOST_DIR}/bin/aarch64-buildroot-linux-gnu-"

    echo "==> Building AIC8800 USB WiFi modules..."
    make -C "${driver_dir}" \
        KDIR="${kernel_dir}" \
        ARCH=arm64 \
        CROSS_COMPILE="${cross_compile}" \
        CONFIG_PLATFORM_UBUNTU=y \
        CONFIG_PLATFORM_ROCKCHIP=n \
        modules

    kernel_release="$(make -s -C "${kernel_dir}" kernelrelease)"
    mod_dest="${TARGET_DIR}/lib/modules/${kernel_release}/kernel/drivers/net/wireless/aic8800"
    firmware_dest="${TARGET_DIR}/lib/firmware/aic8800_fw/USB"

    mkdir -p "${mod_dest}" "${firmware_dest}"
    install -m 0644 \
        "${driver_dir}/aic_load_fw/aic_load_fw.ko" \
        "${driver_dir}/aic8800_fdrv/aic8800_fdrv.ko" \
        "${mod_dest}/"
    cp -a "${AIC8800_REPO}/src/USB/driver_fw/fw/aic8800/." "${firmware_dest}/"
    cp -a "${AIC8800_REPO}/src/USB/driver_fw/fw/aic8800D80/." "${firmware_dest}/"

    echo "==> Staged AIC8800 modules into ${mod_dest}"
    echo "==> Staged AIC8800 firmware into ${firmware_dest}"
}

# Merge device-tree overlays into the base DTB at build time instead of relying on
# U-Boot's runtime `fdtoverlays` (which can fail to apply and break boot on this
# board). The base DTB ships with a __symbols__ table, so fdtoverlay can resolve
# the phandle targets (&i2c0, &i2c0m1_xfer) here on the host.
merge_dt_overlays() {
    local dtb="${TARGET_DIR}/boot/rk3528-rock-2f.dtb"
    local overlay_dir="${TARGET_DIR}/boot/overlay-user"
    # Overlays to bake in (filenames in overlay-user, without path).
    #   rk3528-i2c0-m1 : OLED bus (40-pin header pins 3/5)
    #   pcie-enable    : pcie_en regulator (GPIO1_A4) powering the Firehat's VIA
    #                    VT6315N FireWire controller — without it PCIe never links.
    #   rk3528-pwm0-m0    : PWM0 on GPIO4_C3 for hardware-PWM buzzer drive.
    #   rk3528-spi0-spidev: SPI0 on header pin 19 (MOSI) for RGB LED chain.
    local overlays="rk3528-i2c0-m1.dtbo pcie-enable.dtbo rk3528-pwm0-m0.dtbo rk3528-spi0-spidev.dtbo"

    if ! command -v fdtoverlay >/dev/null 2>&1; then
        echo "ERROR: fdtoverlay not found (install device-tree-compiler)"
        return 1
    fi
    if [ ! -s "$dtb" ]; then
        echo "ERROR: base DTB not found at $dtb"
        return 1
    fi

    for ovl in $overlays; do
        local ovl_path="${overlay_dir}/${ovl}"
        if [ ! -s "$ovl_path" ]; then
            echo "ERROR: overlay $ovl_path missing or empty"
            return 1
        fi
        echo "==> Merging overlay $ovl into base DTB..."
        fdtoverlay -i "$dtb" -o "${dtb}.merged" "$ovl_path"
        mv "${dtb}.merged" "$dtb"
    done

    # Sanity check: confirm i2c@ffa50000 (i2c0) is now enabled.
    if fdtget "$dtb" /i2c@ffa50000 status 2>/dev/null | grep -q okay; then
        echo "==> DTB merge OK: i2c0 status=okay"
    else
        echo "ERROR: i2c0 not enabled after merge"
        return 1
    fi

    # Sanity check: confirm the pcie_en regulator node landed in the DTB.
    if fdtget "$dtb" /pcie-en regulator-name 2>/dev/null | grep -q pcie_en; then
        echo "==> DTB merge OK: pcie_en regulator present"
    else
        echo "ERROR: pcie_en regulator missing after merge"
        return 1
    fi

    # Sanity check: confirm pwm0 (buzzer) is now enabled.
    if fdtget "$dtb" /pwm@ffa90000 status 2>/dev/null | grep -q okay; then
        echo "==> DTB merge OK: pwm0 status=okay"
    else
        echo "ERROR: pwm0 not enabled after merge"
        return 1
    fi

    # Sanity check: confirm SPI0/spidev (RGB LEDs on header pin 19 MOSI) is enabled.
    if fdtget "$dtb" /spi@ff9c0000 status 2>/dev/null | grep -q okay; then
        echo "==> DTB merge OK: spi0 status=okay"
    else
        echo "ERROR: spi0 not enabled after merge"
        return 1
    fi
}

# The generated S40network comes from BR2_SYSTEM_DHCP. It can persist in an
# incremental target tree after the defconfig stops setting that option, and it
# races our AIC8800/WPA-aware S50network script.
if [ -e "${TARGET_DIR}/etc/init.d/S40network" ]; then
    rm -f "${TARGET_DIR}/etc/init.d/S40network"
    echo "==> Removed stale generated S40network; S50network owns Wi-Fi."
fi

# Copy u-boot-rockchip.bin to images/ (buildroot only installs u-boot.bin by default)
UBOOT_ROCKCHIP=$(find "${BUILD_DIR}" -maxdepth 2 -name "u-boot-rockchip.bin" -path "*/uboot-*" 2>/dev/null | head -1)
if [ -n "$UBOOT_ROCKCHIP" ] && [ -s "$UBOOT_ROCKCHIP" ]; then
    cp "$UBOOT_ROCKCHIP" "$IMAGES_DIR/u-boot-rockchip.bin"
    echo "==> Copied u-boot-rockchip.bin to images/"
else
    echo "WARNING: u-boot-rockchip.bin not found or empty in build dir"
fi

ensure_aic8800_repo
build_and_stage_aic8800
# Enable i2c0-m1 (OLED bus on 40-pin header pins 3/5). Verified safe: GPIO4_A0/A1
# are unclaimed on the live board. The earlier "bricks" when enabling i2c0 were
# actually the Python .pyc corruption crashing the app, not a pin conflict.
merge_dt_overlays
