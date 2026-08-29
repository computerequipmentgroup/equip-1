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
grep -q 'start=$2; size=$4' "$s15" || fail "parted -m free-space parser must read start from field 2 and size from field 4"
grep -q 'sgdisk -e "$disk"' "$s15" || fail "provisioning must relocate a compressed-image GPT backup header to the full SD-card size"
grep -q 'repair_gpt_backup_header "$disk"' "$s15" || fail "provisioning must repair GPT before asking parted for free space"
grep -q 'SD fallback partition is missing; attempting first-boot provisioning' "$s15" || fail "boot fallback path must invoke provisioning before using rootfs-backed /data"
grep -q 'BR2_PACKAGE_GPTFDISK=y' src/buildroot/configs/equip1_defconfig || fail "ROCK 2F image must enable gptfdisk for on-device GPT repair"
grep -q 'BR2_PACKAGE_GPTFDISK_SGDISK=y' src/buildroot/configs/equip1_defconfig || fail "ROCK 2F image must install sgdisk for on-device GPT repair"
grep -q 'BR2_PACKAGE_GPTFDISK=y' src/buildroot/configs/equip1_pi5_pisugar3plus_defconfig || fail "Pi 5 image must enable gptfdisk for storage provisioning"
grep -q 'BR2_PACKAGE_GPTFDISK_SGDISK=y' src/buildroot/configs/equip1_pi5_pisugar3plus_defconfig || fail "Pi 5 image must install sgdisk for storage provisioning"

sample_parted_output='BYT;
/dev/mmcblk0:62333952s:sd/mmc:512:512:gpt::;
1:34s:17850s:17817s:free;
1:17851s:2115002s:2097152s:ext4:rootfs:legacy_boot;
1:2115003s:62333918s:60218916s:free;'
parsed_free_region="$(printf '%s\n' "$sample_parted_output" | awk -F: '/:free;$/ { start=$2; size=$4 } END { if (start != "" && size != "") { sub(/s$/, "", start); sub(/s$/, "", size); print start " " size } }')"
[ "$parsed_free_region" = "2115003 60218916" ] || fail "parted parser must select the last free region start/size, got '$parsed_free_region'"

for script in "$s15" "$switcher" "$gadget"; do
  grep -q 'root_part_from_rootfs' "$script" || fail "$script must identify the actual rootfs partition"
  grep -q 'data_num=$((num + 1))' "$script" || fail "$script must use the partition immediately after rootfs for SD recordings storage"
  if grep -q 'echo "${disk}p2"' "$script" || grep -q 'echo "${disk}2"' "$script"; then
    fail "$script still hard-codes p2 for SD recordings storage"
  fi
done

echo "ok - Buildroot SD data provisioning and lookup are present"
