#!/usr/bin/env bash
set -euo pipefail

root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cd "$root"

s15="src/buildroot/overlay/etc/init.d/S15data"
switcher="src/buildroot/overlay/usr/sbin/equip1-storage-switch"
gadget="src/buildroot/overlay/usr/sbin/equip1-usb-storage"

fail() { echo "FAIL: $*" >&2; exit 1; }

grep -q 'provision_sd_data_part' "$s15" || fail "S15data must provision a missing SD data partition on first boot"
grep -q 'mkfs.exfat -n "$DATA_LABEL"' "$s15" || fail "provisioning must format the SD data partition as exFAT with the configured EQUIP1 label"
grep -q 'parted -s "$disk" mkpart recordings' "$s15" || fail "provisioning must create a recordings partition in remaining SD-card space"
grep -q 'SD fallback partition is missing; attempting first-boot provisioning' "$s15" || fail "boot fallback path must invoke provisioning before using rootfs-backed /data"

for script in "$s15" "$switcher" "$gadget"; do
  grep -q 'root_part_from_rootfs' "$script" || fail "$script must identify the actual rootfs partition"
  grep -q 'data_num=$((num + 1))' "$script" || fail "$script must use the partition immediately after rootfs for SD recordings storage"
  if grep -q 'echo "${disk}p2"' "$script" || grep -q 'echo "${disk}2"' "$script"; then
    fail "$script still hard-codes p2 for SD recordings storage"
  fi
done

echo "ok - Buildroot SD data provisioning and lookup are present"
