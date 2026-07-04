#!/usr/bin/env bash
set -euo pipefail

VM_NAME="firehat-builder"
SSH_KEY="$HOME/.ssh/firehat-builder"
SSH_OPTS="-o StrictHostKeyChecking=no -i $SSH_KEY"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
BUILDROOT_DIR="$ROOT_DIR/buildroot"
OUTPUT_DIR="$BUILDROOT_DIR/output"
OVERLAY_DIR="$BUILDROOT_DIR/overlay"
LOG="$BUILDROOT_DIR/build.log"

DEFCONFIG="${1:-firehat_defconfig}"
DEFCONFIG_BASENAME="$(basename "$DEFCONFIG")"
MAX_HEAL_ATTEMPTS="${MAX_HEAL_ATTEMPTS:-3}"
BUILD_JOBS="${BUILD_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)}"
FORCE_KERNEL_CLEAN="${FORCE_KERNEL_CLEAN:-0}"
FORCE_PYTHON_CLEAN="${FORCE_PYTHON_CLEAN:-0}"
FORCE_PYTHON_DEPS="${FORCE_PYTHON_DEPS:-0}"
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

    sedi \
        -e '/^BR2_TOOLCHAIN_BUILDROOT_UCLIBC=y$/d' \
        -e '/^# BR2_TOOLCHAIN_BUILDROOT_GLIBC is not set$/d' \
        -e '/^BR2_KERNEL_HEADERS_6_1=y$/d' \
        -e '/^BR2_TOOLCHAIN_BUILDROOT_GLIBC=y$/d' \
        "$defconfig_path"

    awk '
        BEGIN {
            printed_glibc = 0
            printed_headers = 0
        }
        /^# Toolchain$/ {
            print
            print "BR2_TOOLCHAIN_BUILDROOT_GLIBC=y"
            print "BR2_KERNEL_HEADERS_6_1=y"
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
                print "BR2_KERNEL_HEADERS_6_1=y"
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
        ensure_glibc_defconfig "$BUILDROOT_DIR/configs/$DEFCONFIG_BASENAME"
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

ensure_glibc_defconfig "$BUILDROOT_DIR/configs/$DEFCONFIG_BASENAME"

# Tee all output to log file
exec > >(tee -a "$LOG") 2>&1
echo ""
echo "========== Build started: $(date) =========="

# Copy application source into overlay.
# The desktop repo remains the source of truth; this stages a runnable copy at
# /opt/firehat for the Buildroot image.
echo "==> Copying Firehat application into overlay..."
mkdir -p "$OVERLAY_DIR/opt/firehat"
rm -rf \
    "$OVERLAY_DIR/opt/firehat/firehatd" \
    "$OVERLAY_DIR/opt/firehat/uis" \
    "$OVERLAY_DIR/opt/firehat/fonts" \
    "$OVERLAY_DIR/opt/firehat/requirements.txt"
rsync -a --delete "$ROOT_DIR/firehatd" "$OVERLAY_DIR/opt/firehat/"
rsync -a --delete \
    --exclude 'web/node_modules' \
    --exclude 'web/.nuxt' \
    "$ROOT_DIR/uis" "$OVERLAY_DIR/opt/firehat/"
rsync -a --delete "$ROOT_DIR/fonts" "$OVERLAY_DIR/opt/firehat/"
cp "$ROOT_DIR/requirements.txt" "$OVERLAY_DIR/opt/firehat/requirements.txt"

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

    if [ "$attempt" -gt 1 ]; then
        attempt_force_kernel_clean=1
        attempt_force_python_clean=1
        attempt_force_python_deps=1
    fi

    echo "==> Syncing files to VM for attempt $attempt/$MAX_HEAL_ATTEMPTS..."
    rsync -avz -e "ssh $SSH_OPTS" \
        "$OVERLAY_DIR/" admin@"$VM_IP":~/overlay/

    rsync -avz -e "ssh $SSH_OPTS" \
        "$BUILDROOT_DIR/configs/" "$BUILDROOT_DIR/dts/" \
        admin@"$VM_IP":~/staging/

    # br2-external tree with the vendored DV capture stack (dvgrab + libs)
    rsync -avz --delete -e "ssh $SSH_OPTS" \
        "$BUILDROOT_DIR/external/" admin@"$VM_IP":~/external/

    scp $SSH_OPTS "$BUILDROOT_DIR/scripts/post-build.sh" admin@"$VM_IP":~/staging/post-build.sh

    echo "==> Building on VM (attempt $attempt/$MAX_HEAL_ATTEMPTS)..."
    $SSH \
        DEFCONFIG_BASENAME="$DEFCONFIG_BASENAME" \
        BUILD_JOBS="$BUILD_JOBS" \
        FORCE_KERNEL_CLEAN="$attempt_force_kernel_clean" \
        FORCE_PYTHON_CLEAN="$attempt_force_python_clean" \
        FORCE_PYTHON_DEPS="$attempt_force_python_deps" \
        CORRUPT_KERNEL_THRESHOLD="$CORRUPT_KERNEL_THRESHOLD" \
        bash -s <<'BUILDSSH'
set -euo pipefail

DEFCONFIG_BASENAME="${DEFCONFIG_BASENAME:-firehat_defconfig}"
BUILD_JOBS="${BUILD_JOBS:-4}"
FORCE_KERNEL_CLEAN="${FORCE_KERNEL_CLEAN:-0}"
FORCE_PYTHON_CLEAN="${FORCE_PYTHON_CLEAN:-0}"
FORCE_PYTHON_DEPS="${FORCE_PYTHON_DEPS:-0}"
CORRUPT_KERNEL_THRESHOLD="${CORRUPT_KERNEL_THRESHOLD:-50}"

hash_file() {
    sha256sum "$1" | awk '{print $1}'
}

# Compile DTS overlays
mkdir -p ~/overlay/boot/overlay-user
for dts in ~/staging/*.dts; do
    [ -f "$dts" ] || continue
    name=$(basename "$dts" .dts)
    echo "  Compiling $name.dtbo..."
    dtc -I dts -O dtb -o ~/overlay/boot/overlay-user/"$name".dtbo "$dts"
done
echo "==> DTS overlays compiled."

# Install Python dependencies into overlay
if [ -f ~/overlay/opt/firehat/requirements.txt ]; then
    REQUIREMENTS_HASH="$(hash_file ~/overlay/opt/firehat/requirements.txt)"
    REQUIREMENTS_STAMP=~/overlay/opt/firehat/.requirements.sha256
    if [ "$FORCE_PYTHON_DEPS" = "1" ] \
        || [ ! -d ~/overlay/opt/firehat/lib ] \
        || [ ! -f "$REQUIREMENTS_STAMP" ] \
        || [ "$(cat "$REQUIREMENTS_STAMP" 2>/dev/null)" != "$REQUIREMENTS_HASH" ]; then
        python3 -m venv /tmp/firehat-venv
        /tmp/firehat-venv/bin/pip install --upgrade \
            --target ~/overlay/opt/firehat/lib \
            -r ~/overlay/opt/firehat/requirements.txt
        echo "$REQUIREMENTS_HASH" > "$REQUIREMENTS_STAMP"
        echo "==> Python deps installed."
    else
        echo "==> Python deps unchanged; reusing cached overlay libs."
    fi
fi

# Copy configs into buildroot source tree
cp ~/staging/"$DEFCONFIG_BASENAME" ~/buildroot/configs/
cp ~/staging/linux.config ~/buildroot/
if [ -f ~/staging/u-boot.config ]; then
    cp ~/staging/u-boot.config ~/buildroot/
fi
cp ~/staging/genimage.cfg ~/buildroot/
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

if [ "$FORCE_PYTHON_CLEAN" = "1" ]; then
    echo "==> Cleaning Python build so SSL/zlib extensions are rebuilt..."
    make python3-dirclean 2>/dev/null || true
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
echo "    Flash with: ./buildroot/scripts/flash.sh"
echo "========== Build finished: $(date) =========="
