#!/usr/bin/env bash
set -euo pipefail

VM_NAME="equip1-builder"
SSH_KEY="$HOME/.ssh/equip1-builder"
SSH_OPTS="-o StrictHostKeyChecking=no -i $SSH_KEY"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
BUILDROOT_DIR="$ROOT_DIR/buildroot"
OUTPUT_DIR="$BUILDROOT_DIR/output"
OVERLAY_DIR="$BUILDROOT_DIR/overlay"
LOG="$BUILDROOT_DIR/build.log"

DEFCONFIG="${1:-equip1_defconfig}"
DEFCONFIG_BASENAME="$(basename "$DEFCONFIG")"
case "$DEFCONFIG_BASENAME" in
    *pi5*)
        TARGET_BOARD="pi5"
        KERNEL_HEADERS_LINE="BR2_PACKAGE_HOST_LINUX_HEADERS_CUSTOM_6_6=y"
        POST_BUILD_SCRIPT="post-build-pi5.sh"
        GENIMAGE_CFG="genimage-pi5.cfg"
        ;;
    *)
        TARGET_BOARD="rock2f"
        KERNEL_HEADERS_LINE="BR2_KERNEL_HEADERS_6_1=y"
        POST_BUILD_SCRIPT="post-build.sh"
        GENIMAGE_CFG="genimage.cfg"
        ;;
esac
MAX_HEAL_ATTEMPTS="${MAX_HEAL_ATTEMPTS:-3}"
BUILD_JOBS="${BUILD_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)}"
FORCE_KERNEL_CLEAN="${FORCE_KERNEL_CLEAN:-0}"
FORCE_PYTHON_CLEAN="${FORCE_PYTHON_CLEAN:-0}"
FORCE_PYTHON_DEPS="${FORCE_PYTHON_DEPS:-0}"
FORCE_FFMPEG_CLEAN="${FORCE_FFMPEG_CLEAN:-0}"
CORRUPT_KERNEL_THRESHOLD="${CORRUPT_KERNEL_THRESHOLD:-50}"

mkdir -p "$OUTPUT_DIR"

sedi() {
    if sed --version >/dev/null 2>&1; then
        sed -i "$@"
    else
        sed -i '' "$@"
    fi
}

ensure_glibc_defconfig() {
    local defconfig_path="$1"
    local kernel_headers_line="${2:-BR2_KERNEL_HEADERS_6_1=y}"

    sedi \
        -e '/^BR2_TOOLCHAIN_BUILDROOT_UCLIBC=y$/d' \
        -e '/^# BR2_TOOLCHAIN_BUILDROOT_GLIBC is not set$/d' \
        -e '/^BR2_KERNEL_HEADERS_6_1=y$/d' \
        -e '/^BR2_PACKAGE_HOST_LINUX_HEADERS_CUSTOM_6_6=y$/d' \
        -e '/^BR2_TOOLCHAIN_BUILDROOT_GLIBC=y$/d' \
        "$defconfig_path"

    awk -v kernel_headers_line="$kernel_headers_line" '
        BEGIN {
            printed_glibc = 0
            printed_headers = 0
        }
        /^# Toolchain$/ {
            print
            print "BR2_TOOLCHAIN_BUILDROOT_GLIBC=y"
            print kernel_headers_line
            printed_glibc = 1
            printed_headers = 1
            next
        }
        { print }
        END {
            if (!printed_glibc) {
                print "BR2_TOOLCHAIN_BUILDROOT_GLIBC=y"
            }
            if (!printed_headers) {
                print kernel_headers_line
            }
        }
    ' "$defconfig_path" > "$defconfig_path.tmp"
    mv "$defconfig_path.tmp" "$defconfig_path"
}

remove_drm_override() {
    local kernel_fragment="$1"

    if grep -q '^CONFIG_DRM=n$' "$kernel_fragment"; then
        sedi '/^CONFIG_DRM=n$/d' "$kernel_fragment"
        return 0
    fi

    return 1
}

apply_self_heal() {
    local attempt_log="$1"
    local healed=false

    if grep -q 'defconfig resolved to uclibc instead of glibc' "$attempt_log"; then
        ensure_glibc_defconfig "$BUILDROOT_DIR/configs/$DEFCONFIG_BASENAME" "$KERNEL_HEADERS_LINE"
        echo "==> Self-heal: reasserted glibc toolchain settings in $DEFCONFIG_BASENAME"
        healed=true
    fi

    if grep -Eq 'rkx110_x120_panel\.o|undefined reference to `drm_|Unexpected GOT/PLT entries detected!' "$attempt_log"; then
        if remove_drm_override "$BUILDROOT_DIR/configs/linux.config"; then
            echo "==> Self-heal: removed CONFIG_DRM=n override from linux.config"
            healed=true
        fi
    fi

    $healed
}

ensure_glibc_defconfig "$BUILDROOT_DIR/configs/$DEFCONFIG_BASENAME" "$KERNEL_HEADERS_LINE"

# Tee all output to log file
exec > >(tee -a "$LOG") 2>&1
echo ""
echo "========== Build started: $(date) =========="
echo "==> Target board: $TARGET_BOARD ($DEFCONFIG_BASENAME)"

# Build the web UI into a static bundle on the host before staging it.
# equip1d serves the captured files and dashboard from src/uis/web/.output/public,
# so a fresh `nuxt generate` must run before the overlay is assembled — the
# Buildroot build itself only copies the generated output, it does not build it.
WEB_DIR="$ROOT_DIR/uis/web"
if [ -f "$WEB_DIR/package.json" ]; then
    if ! command -v npm >/dev/null 2>&1; then
        echo "ERROR: npm is required to build the web UI but was not found on PATH."
        exit 1
    fi
    echo "==> Building web UI (nuxt generate)..."
    if [ -d "$WEB_DIR/node_modules" ]; then
        ( cd "$WEB_DIR" && npm install --no-audit --no-fund )
    else
        ( cd "$WEB_DIR" && npm ci --no-audit --no-fund )
    fi
    ( cd "$WEB_DIR" && rm -rf .output .nuxt && npm run generate )
    if [ ! -f "$WEB_DIR/.output/public/index.html" ]; then
        echo "ERROR: nuxt generate did not produce .output/public/index.html"
        exit 1
    fi
    echo "==> Web UI built: $WEB_DIR/.output/public"
fi

# Copy application source into overlay.
# The desktop repo remains the source of truth; this stages a runnable copy at
# /opt/equip1 for the Buildroot image.
echo "==> Copying Equip-1 application into overlay..."
mkdir -p "$OVERLAY_DIR/opt/equip1"
rm -rf \
    "$OVERLAY_DIR/opt/equip1/equip1d" \
    "$OVERLAY_DIR/opt/equip1/uis" \
    "$OVERLAY_DIR/opt/equip1/fonts" \
    "$OVERLAY_DIR/opt/equip1/requirements.txt"
rsync -a --delete "$ROOT_DIR/equip1d" "$OVERLAY_DIR/opt/equip1/"
rsync -a --delete \
    --exclude 'web/node_modules' \
    --exclude 'web/.nuxt' \
    --exclude 'web/dist' \
    "$ROOT_DIR/uis" "$OVERLAY_DIR/opt/equip1/"
rsync -a --delete "$ROOT_DIR/fonts" "$OVERLAY_DIR/opt/equip1/"
cp "$ROOT_DIR/requirements.txt" "$OVERLAY_DIR/opt/equip1/requirements.txt"

GIT_ROOT="$(git -C "$ROOT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$GIT_ROOT" ]; then
    GIT_COMMIT="$(git -C "$GIT_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
    GIT_TAG="$(git -C "$GIT_ROOT" describe --tags --exact-match HEAD 2>/dev/null || true)"
    GIT_VERSION_TAG="${EQUIP1_VERSION_TAG:-${GIT_TAG:-$(git -C "$GIT_ROOT" describe --tags --match 'v[0-9]*' --abbrev=0 2>/dev/null || echo v0.1.0)}}"
    GIT_BRANCH="$(git -C "$GIT_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
    GIT_DIRTY="$(git -C "$GIT_ROOT" diff --quiet --ignore-submodules HEAD -- 2>/dev/null && echo false || echo true)"
    cat > "$OVERLAY_DIR/opt/equip1/version.json" <<EOF
{
  "version": "${GIT_VERSION_TAG}",
  "tag": "${GIT_VERSION_TAG}",
  "commit": "$GIT_COMMIT",
  "branch": "$GIT_BRANCH",
  "dirty": $GIT_DIRTY,
  "built_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "repo": "computerequipmentgroup/equip-1"
}
EOF
fi

stage_pisugar_manager() {
    local version="${PISUGAR_VERSION:-v2.3.2}"
    local url="https://github.com/PiSugar/pisugar-power-manager-rs/releases/download/${version}/pisugar_aarch64-unknown-linux-musl.tar.gz"
    local tmp
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' RETURN

    echo "==> Staging PiSugar power manager (${version})..."
    curl -L --fail -sS -o "$tmp/pisugar.tar.gz" "$url"
    tar -xzf "$tmp/pisugar.tar.gz" -C "$tmp"
    local src="$tmp/aarch64-unknown-linux-musl"

    mkdir -p "$OVERLAY_DIR/usr/bin" "$OVERLAY_DIR/etc/pisugar-server" "$OVERLAY_DIR/etc/default"
    cp "$src/pisugar-server" "$OVERLAY_DIR/usr/bin/pisugar-server"
    chmod 0755 "$OVERLAY_DIR/usr/bin/pisugar-server"
    cp "$src/pisugar-server-conf/config.json" "$OVERLAY_DIR/etc/pisugar-server/config.json"
    chmod 0644 "$OVERLAY_DIR/etc/pisugar-server/config.json"
    cp "$src/pisugar-server-conf/pisugar-server.default" "$OVERLAY_DIR/etc/default/pisugar-server"
    chmod 0644 "$OVERLAY_DIR/etc/default/pisugar-server"
    rsync -a --delete "$src/web-ui/" "$OVERLAY_DIR/usr/share/pisugar-server/web/"
    # The upstream default still names a PiSugar 2 variant; force the model used
    # by PiSugar 3 Plus boards. The server model name is "PiSugar 3".
    sedi "s|'PiSugar 2 (2-LEDs)'|'PiSugar 3'|g" "$OVERLAY_DIR/etc/default/pisugar-server"
}

stage_pisugar_manager

# Start VM if not running
echo "==> Starting VM..."
tart run --no-graphics "$VM_NAME" 2>/dev/null &
VM_PID=$!
sleep 10

VM_IP=""
SSH_OK=false
for i in $(seq 1 60); do
    VM_IP=$(tart ip "$VM_NAME" 2>/dev/null || true)
    if [ -n "$VM_IP" ]; then
        if ssh $SSH_OPTS -o ConnectTimeout=5 admin@"$VM_IP" true 2>/dev/null; then
            SSH_OK=true
            break
        fi
    fi
    echo "  waiting for SSH... ($i/60)"
    sleep 5
done

if [ "$SSH_OK" != "true" ]; then
    echo "ERROR: Could not establish SSH to VM (IP: ${VM_IP:-none})."
    kill $VM_PID 2>/dev/null || true
    exit 1
fi

echo "==> VM IP: $VM_IP"
SSH="ssh $SSH_OPTS admin@$VM_IP"

run_build_attempt() {
    local attempt="$1"
    local attempt_force_kernel_clean="$FORCE_KERNEL_CLEAN"
    local attempt_force_python_clean="$FORCE_PYTHON_CLEAN"
    local attempt_force_python_deps="$FORCE_PYTHON_DEPS"
    local attempt_force_ffmpeg_clean="$FORCE_FFMPEG_CLEAN"

    if [ "$attempt" -gt 1 ]; then
        attempt_force_kernel_clean=1
        attempt_force_python_clean=1
        attempt_force_python_deps=1
        attempt_force_ffmpeg_clean=1
    fi

    echo "==> Syncing files to VM for attempt $attempt/$MAX_HEAL_ATTEMPTS..."
    rsync -avz --delete \
        --exclude '/opt/equip1/lib/' \
        --exclude '/opt/equip1/.requirements.sha256' \
        -e "ssh $SSH_OPTS" \
        "$OVERLAY_DIR/" admin@"$VM_IP":~/overlay/

    rsync -avz -e "ssh $SSH_OPTS" \
        "$BUILDROOT_DIR/configs/" "$BUILDROOT_DIR/dts/" \
        admin@"$VM_IP":~/staging/

    # br2-external tree with the vendored DV capture stack (dvgrab + libs)
    rsync -avz --delete -e "ssh $SSH_OPTS" \
        "$BUILDROOT_DIR/external/" admin@"$VM_IP":~/external/

    scp $SSH_OPTS "$BUILDROOT_DIR/scripts/$POST_BUILD_SCRIPT" admin@"$VM_IP":~/staging/post-build.sh

    echo "==> Building on VM (attempt $attempt/$MAX_HEAL_ATTEMPTS)..."
    $SSH \
        DEFCONFIG_BASENAME="$DEFCONFIG_BASENAME" \
        TARGET_BOARD="$TARGET_BOARD" \
        GENIMAGE_CFG="$GENIMAGE_CFG" \
        BUILD_JOBS="$BUILD_JOBS" \
        FORCE_KERNEL_CLEAN="$attempt_force_kernel_clean" \
        FORCE_PYTHON_CLEAN="$attempt_force_python_clean" \
        FORCE_PYTHON_DEPS="$attempt_force_python_deps" \
        FORCE_FFMPEG_CLEAN="$attempt_force_ffmpeg_clean" \
        CORRUPT_KERNEL_THRESHOLD="$CORRUPT_KERNEL_THRESHOLD" \
        bash -s <<'BUILDSSH'
set -euo pipefail

DEFCONFIG_BASENAME="${DEFCONFIG_BASENAME:-equip1_defconfig}"
TARGET_BOARD="${TARGET_BOARD:-rock2f}"
GENIMAGE_CFG="${GENIMAGE_CFG:-genimage.cfg}"
BUILD_JOBS="${BUILD_JOBS:-4}"
FORCE_KERNEL_CLEAN="${FORCE_KERNEL_CLEAN:-0}"
FORCE_PYTHON_CLEAN="${FORCE_PYTHON_CLEAN:-0}"
FORCE_PYTHON_DEPS="${FORCE_PYTHON_DEPS:-0}"
FORCE_FFMPEG_CLEAN="${FORCE_FFMPEG_CLEAN:-0}"
CORRUPT_KERNEL_THRESHOLD="${CORRUPT_KERNEL_THRESHOLD:-50}"

hash_file() {
    sha256sum "$1" | awk '{print $1}'
}

# Compile Rockchip DTS overlays. Raspberry Pi boot uses firmware overlays from
# rpi-firmware instead.
if [ "$TARGET_BOARD" = "rock2f" ]; then
    mkdir -p ~/overlay/boot/overlay-user
    for dts in ~/staging/*.dts; do
        [ -f "$dts" ] || continue
        name=$(basename "$dts" .dts)
        echo "  Compiling $name.dtbo..."
        dtc -I dts -O dtb -o ~/overlay/boot/overlay-user/"$name".dtbo "$dts"
    done
    echo "==> DTS overlays compiled."
fi

# Install Python dependencies into overlay
if [ -f ~/overlay/opt/equip1/requirements.txt ]; then
    REQUIREMENTS_HASH="$(hash_file ~/overlay/opt/equip1/requirements.txt)"
    REQUIREMENTS_STAMP=~/overlay/opt/equip1/.requirements.sha256
    if [ "$FORCE_PYTHON_DEPS" = "1" ] \
        || [ ! -d ~/overlay/opt/equip1/lib ] \
        || [ ! -f "$REQUIREMENTS_STAMP" ] \
        || [ "$(cat "$REQUIREMENTS_STAMP" 2>/dev/null)" != "$REQUIREMENTS_HASH" ]; then
        python3 -m venv /tmp/equip1-venv
        /tmp/equip1-venv/bin/pip install --upgrade \
            --target ~/overlay/opt/equip1/lib \
            -r ~/overlay/opt/equip1/requirements.txt
        echo "$REQUIREMENTS_HASH" > "$REQUIREMENTS_STAMP"
        echo "==> Python deps installed."
    else
        echo "==> Python deps unchanged; reusing cached overlay libs."
    fi
fi

# Copy configs into buildroot source tree
cp ~/staging/"$DEFCONFIG_BASENAME" ~/buildroot/configs/
if [ "$TARGET_BOARD" = "pi5" ]; then
    cp ~/staging/linux-pi5.config ~/buildroot/
    cp ~/staging/config_5_pisugar.txt ~/buildroot/
    cp ~/staging/cmdline_5.txt ~/buildroot/
else
    cp ~/staging/linux.config ~/buildroot/
    if [ -f ~/staging/u-boot.config ]; then
        cp ~/staging/u-boot.config ~/buildroot/
    fi
fi
cp ~/staging/"$GENIMAGE_CFG" ~/buildroot/genimage.cfg
cp ~/staging/post-build.sh ~/buildroot/
chmod +x ~/buildroot/post-build.sh

cd ~/buildroot

# br2-external tree providing the vendored DV capture packages (dvgrab + libs).
export BR2_EXTERNAL="$HOME/external"

# Always reload defconfig to pick up changes
echo "==> Loading defconfig..."
make BR2_EXTERNAL="$BR2_EXTERNAL" "$DEFCONFIG_BASENAME"
# Patch paths to use absolute VM paths
sed -i "s|^BR2_ROOTFS_OVERLAY=.*|BR2_ROOTFS_OVERLAY=\"$HOME/overlay\"|" .config
sed -i "s|^BR2_LINUX_KERNEL_CONFIG_FRAGMENT_FILES=.*|BR2_LINUX_KERNEL_CONFIG_FRAGMENT_FILES=\"$HOME/buildroot/linux.config\"|" .config
sed -i "s|^BR2_TARGET_UBOOT_CONFIG_FRAGMENT_FILES=.*|BR2_TARGET_UBOOT_CONFIG_FRAGMENT_FILES=\"$HOME/buildroot/u-boot.config\"|" .config
sed -i "s|RKBIN_PATH|$HOME/rkbin|g" .config
sed -i "s|^BR2_ROOTFS_POST_BUILD_SCRIPT=.*|BR2_ROOTFS_POST_BUILD_SCRIPT=\"$HOME/buildroot/post-build.sh\"|" .config
sed -i "s|BR2_ROOTFS_POST_SCRIPT_ARGS=.*|BR2_ROOTFS_POST_SCRIPT_ARGS=\"-c $HOME/buildroot/genimage.cfg\"|" .config
sed -i \
    -e '/^BR2_TOOLCHAIN_BUILDROOT_UCLIBC=y$/d' \
    -e '/^BR2_TOOLCHAIN_USES_UCLIBC=y$/d' \
    -e '/^BR2_TOOLCHAIN_BUILDROOT_LIBC="uclibc"$/d' \
    -e '/^# BR2_TOOLCHAIN_BUILDROOT_GLIBC is not set$/d' \
    -e '/^# BR2_TOOLCHAIN_USES_GLIBC is not set$/d' \
    -e '/^BR2_TOOLCHAIN_BUILDROOT_GLIBC=y$/d' \
    -e '/^BR2_TOOLCHAIN_USES_GLIBC=y$/d' \
    -e '/^BR2_TOOLCHAIN_BUILDROOT_LIBC="glibc"$/d' \
    .config
cat >> .config <<'EOF'
BR2_TOOLCHAIN_BUILDROOT_GLIBC=y
BR2_TOOLCHAIN_USES_GLIBC=y
BR2_TOOLCHAIN_BUILDROOT_LIBC="glibc"
# BR2_TOOLCHAIN_BUILDROOT_UCLIBC is not set
# BR2_TOOLCHAIN_USES_UCLIBC is not set
EOF
make olddefconfig

# Verify toolchain is glibc, not uclibc
if ! grep -q '^BR2_TOOLCHAIN_BUILDROOT_GLIBC=y$' .config \
    || ! grep -q '^BR2_TOOLCHAIN_BUILDROOT_LIBC="glibc"$' .config \
    || grep -q '^BR2_TOOLCHAIN_BUILDROOT_UCLIBC=y$' .config; then
    echo "ERROR: defconfig did not resolve to glibc. Check defconfig."
    grep -E 'BR2_TOOLCHAIN_(USES|BUILDROOT)_(GLIBC|UCLIBC)|BR2_TOOLCHAIN_BUILDROOT_LIBC|BR2_KERNEL_HEADERS_' .config | head -20
    exit 1
fi
echo "==> Config verified: $(grep 'BR2_TOOLCHAIN_BUILDROOT_LIBC=' .config)"
if grep -q '^BR2_PACKAGE_PYTHON3_SSL=y$' .config; then
    echo "==> Config verified: Python SSL enabled"
else
    echo "ERROR: BR2_PACKAGE_PYTHON3_SSL is not enabled after olddefconfig"
    exit 1
fi
if grep -q '^BR2_PACKAGE_PYTHON3_ZLIB=y$' .config; then
    echo "==> Config verified: Python zlib enabled"
else
    echo "ERROR: BR2_PACKAGE_PYTHON3_ZLIB is not enabled after olddefconfig"
    exit 1
fi
if grep -q '^BR2_PACKAGE_HOSTAPD=y$' .config; then
    echo "==> Config verified: hostapd enabled"
else
    echo "ERROR: BR2_PACKAGE_HOSTAPD is not enabled after olddefconfig"
    exit 1
fi
if grep -q '^BR2_PACKAGE_DNSMASQ=y$' .config; then
    echo "==> Config verified: dnsmasq enabled"
else
    echo "ERROR: BR2_PACKAGE_DNSMASQ is not enabled after olddefconfig"
    exit 1
fi
if grep -q '^BR2_PACKAGE_CA_CERTIFICATES=y$' .config; then
    echo "==> Config verified: CA certificates enabled for updater HTTPS"
else
    echo "ERROR: BR2_PACKAGE_CA_CERTIFICATES is not enabled after olddefconfig"
    exit 1
fi
if grep -q '^BR2_PACKAGE_FFMPEG_SWSCALE=y$' .config; then
    echo "==> Config verified: ffmpeg swscale enabled"
else
    echo "ERROR: BR2_PACKAGE_FFMPEG_SWSCALE is not enabled after olddefconfig"
    exit 1
fi
if grep -q '^BR2_PACKAGE_FFMPEG_OUTDEVS=y$' .config; then
    echo "==> Config verified: ffmpeg output devices enabled"
else
    echo "ERROR: BR2_PACKAGE_FFMPEG_OUTDEVS is not enabled after olddefconfig"
    exit 1
fi
if grep -q '^BR2_PACKAGE_FFMPEG_GPL=y$' .config; then
    echo "==> Config verified: ffmpeg GPL filters enabled"
else
    echo "ERROR: BR2_PACKAGE_FFMPEG_GPL is not enabled after olddefconfig"
    exit 1
fi
if [ "$FORCE_PYTHON_CLEAN" = "1" ]; then
    echo "==> Cleaning Python build so SSL/zlib extensions are rebuilt..."
    make python3-dirclean 2>/dev/null || true
fi

# Buildroot does not rebuild a package when only a Config.in option changes, so a
# previously-built ffmpeg can linger with required features disabled (breaking
# thumbnails, HDMI output, or NNEDI deinterlacing). Self-heal by forcing a clean
# when the built binary disagrees with the current .config.
FFMPEG_TARGET_BIN=output/target/usr/bin/ffmpeg
if grep -q '^BR2_PACKAGE_FFMPEG_SWSCALE=y$' .config \
    && [ -f "$FFMPEG_TARGET_BIN" ] \
    && grep -a -q -- '--disable-swscale' "$FFMPEG_TARGET_BIN"; then
    echo "==> ffmpeg was built without swscale but config now enables it; forcing rebuild."
    FORCE_FFMPEG_CLEAN=1
fi
if grep -q '^BR2_PACKAGE_FFMPEG_OUTDEVS=y$' .config \
    && [ -f "$FFMPEG_TARGET_BIN" ] \
    && grep -a -q -- '--disable-outdevs' "$FFMPEG_TARGET_BIN"; then
    echo "==> ffmpeg was built without output devices but config now enables them; forcing rebuild."
    FORCE_FFMPEG_CLEAN=1
fi
if grep -q '^BR2_PACKAGE_FFMPEG_GPL=y$' .config \
    && [ -f "$FFMPEG_TARGET_BIN" ] \
    && grep -a -q -- '--disable-gpl' "$FFMPEG_TARGET_BIN"; then
    echo "==> ffmpeg was built without GPL filters but config now enables them; forcing rebuild."
    FORCE_FFMPEG_CLEAN=1
fi
if [ "$FORCE_FFMPEG_CLEAN" = "1" ]; then
    echo "==> Cleaning ffmpeg build so required features are rebuilt..."
    make ffmpeg-dirclean 2>/dev/null || true
fi

if [ "$FORCE_KERNEL_CLEAN" = "1" ]; then
    for kdir in output/build/linux-*/; do
        if [ -d "$kdir" ]; then
            echo "==> Cleaning kernel build for fresh reconfigure..."
            make linux-dirclean 2>/dev/null || true
            break
        fi
    done
else
    echo "==> Reusing existing kernel build tree when possible."
fi

# Clean corrupted build artifacts (0-byte .o/.a files from interrupted builds)
for builddir in output/build/linux-* output/build/uboot-*; do
    [ -d "$builddir" ] || continue
    CORRUPT_COUNT=0
    while IFS= read -r -d '' f; do
        CORRUPT_COUNT=$((CORRUPT_COUNT + 1))
        rm -f "$f"
    done < <(find "$builddir" \( -name "*.o" -o -name "*.a" \) -size 0 -print0 2>/dev/null)
    if [ "$CORRUPT_COUNT" -gt 0 ]; then
        echo "==> Cleaned $CORRUPT_COUNT corrupted object file(s) in $(basename "$builddir")"
        if [ "$CORRUPT_COUNT" -ge "$CORRUPT_KERNEL_THRESHOLD" ] && [ -d "$builddir" ] && [ "${builddir#output/build/linux-}" != "$builddir" ]; then
            echo "==> Too many corrupted kernel objects; forcing linux-dirclean for a safer rebuild."
            make linux-dirclean 2>/dev/null || true
            break
        fi
        # Remove build stamp so buildroot re-runs the build step
        rm -f "$builddir/.stamp_built" "$builddir/.stamp_images_installed" "$builddir/.stamp_target_installed"
        # Also remove stale .cmd files and generated C files so they get rebuilt
        find "$builddir" -name ".*.cmd" -newer "$builddir/.stamp_configured" -delete 2>/dev/null || true
        find "$builddir" -name "oid_registry_data.c" -delete 2>/dev/null || true
    fi
done

echo "==> Building..."
make -j"$BUILD_JOBS"

echo "==> Build complete."
ls -lh output/images/
BUILDSSH
}

attempt=1
while true; do
    ATTEMPT_LOG="$(mktemp "${TMPDIR:-/tmp}/equip1-build-attempt-${attempt}.log.XXXXXX")"
    if run_build_attempt "$attempt" 2>&1 | tee "$ATTEMPT_LOG"; then
        rm -f "$ATTEMPT_LOG"
        break
    fi

    if [ "$attempt" -ge "$MAX_HEAL_ATTEMPTS" ]; then
        echo "ERROR: Build failed after $attempt attempt(s); no retries remain."
        echo "Last attempt log: $ATTEMPT_LOG"
        exit 1
    fi

    if ! apply_self_heal "$ATTEMPT_LOG"; then
        echo "ERROR: Build failed with an unknown pattern; stopping for manual investigation."
        echo "Last attempt log: $ATTEMPT_LOG"
        exit 1
    fi

    rm -f "$ATTEMPT_LOG"
    attempt=$((attempt + 1))
done

echo "==> Copying image to host..."
scp $SSH_OPTS \
    admin@"$VM_IP":~/buildroot/output/images/sdcard.img \
    "$OUTPUT_DIR/sdcard.img"

echo "==> Stopping VM..."
# Flush the guest filesystem before stopping. tart stop can otherwise lose
# recently-written files (truncated/0-byte), corrupting cached build state
# (e.g. the AIC8800 git checkout) for the next run.
$SSH 'sync; sync' 2>/dev/null || true
tart stop "$VM_NAME" 2>/dev/null || true
wait $VM_PID 2>/dev/null || true

echo ""
echo "==> Image ready: $OUTPUT_DIR/sdcard.img"
echo "    Size: $(du -h "$OUTPUT_DIR/sdcard.img" | cut -f1)"
echo "    Flash with: ./src/buildroot/scripts/flash.sh"
echo "========== Build finished: $(date) =========="
