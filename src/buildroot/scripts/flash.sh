#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="$ROOT_DIR/buildroot/output/sdcard.img"

if [ ! -f "$IMAGE" ]; then
    echo "ERROR: No image found at $IMAGE"
    echo "Run ./src/buildroot/scripts/build.sh first."
    exit 1
fi

# List removable disks: external drives AND internal removable media
# (built-in SD card readers report as "internal" but "Removable").
DISKS=()
for d in $(diskutil list physical 2>/dev/null | grep "^/dev/" | awk '{print $1}'); do
    INFO=$(diskutil info "$d")
    LOCATION=$(echo "$INFO" | awk -F: '/Device Location/{print $2}' | xargs)
    REMOVABLE=$(echo "$INFO" | awk -F: '/Removable Media/{print $2}' | xargs)
    if [ "$LOCATION" = "External" ] || echo "$REMOVABLE" | grep -qi "Removable"; then
        DISKS+=("$d")
    fi
done

if [ ${#DISKS[@]} -eq 0 ]; then
    echo "ERROR: No removable disks found. Insert SD card and try again."
    exit 1
fi

echo "Removable disks:"
echo ""
for i in "${!DISKS[@]}"; do
    INFO=$(diskutil info "${DISKS[$i]}")
    SIZE=$(echo "$INFO" | grep "Disk Size" | awk -F: '{print $2}' | xargs)
    NAME=$(echo "$INFO" | grep "Media Name" | awk -F: '{print $2}' | xargs)
    PROTO=$(echo "$INFO" | grep "Protocol" | awk -F: '{print $2}' | xargs)
    echo "  [$i] ${DISKS[$i]}  $NAME  $SIZE  ($PROTO)"
done
echo ""
read -p "Select disk to flash: " SEL
DISK="${DISKS[$SEL]}"

SIZE=$(diskutil info "$DISK" | grep "Disk Size" | awk -F: '{print $2}' | xargs)
echo ""
echo "WARNING: This will ERASE all data on $DISK ($SIZE)"
echo "Image: $IMAGE ($(du -h "$IMAGE" | cut -f1))"
echo ""
read -p "Type 'yes' to continue: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

echo "==> Unmounting $DISK..."
diskutil unmountDisk "$DISK" || true

RAW_DISK="${DISK/disk/rdisk}"
echo "==> Flashing to $RAW_DISK..."
sudo dd if="$IMAGE" of="$RAW_DISK" bs=1M status=progress
sync

# --- Create the recordings partition (exFAT) filling the rest of the card ---
# The image only contains the ~1GB system partition; here we expand the GPT to
# the full card and add a second partition formatted exFAT (readable on
# macOS/Windows/Linux), labeled EQUIP1. Done on the unmounted card so it's clean.
if command -v sgdisk >/dev/null 2>&1; then
    echo "==> Creating recordings partition (exFAT) on the rest of the card..."
    diskutil unmountDisk "$DISK" >/dev/null 2>&1 || true
    sudo sgdisk -e "$DISK" >/dev/null 2>&1 || true          # expand GPT to full card
    sudo sgdisk -n 2:0:0 -t 2:0700 -c 2:recordings "$DISK"  # add partition 2 = MS basic data
    sync
    diskutil unmountDisk "$DISK" >/dev/null 2>&1 || true    # force macOS to re-read the table
    sleep 2
    PART2="${DISK}s2"
    RAW_PART2="${RAW_DISK}s2"
    if [ -e "$PART2" ]; then
        echo "==> Formatting $PART2 as exFAT (label EQUIP1)..."
        sudo newfs_exfat -v EQUIP1 "$RAW_PART2"
        sync
    else
        echo "WARNING: $PART2 did not appear; recordings partition not formatted."
        echo "         (The board will create it on first boot as a fallback.)"
    fi
else
    echo "NOTE: sgdisk not found; skipping recordings-partition creation."
    echo "      Install with: brew install gptfdisk"
fi

echo "==> Ejecting..."
diskutil eject "$DISK"

echo "==> Done. Insert SD card into ROCK 2F and power on."
echo "    The card now has: system partition + EQUIP1 (exFAT) recordings partition."
