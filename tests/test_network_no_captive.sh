#!/usr/bin/env bash
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }

network_script=src/buildroot/overlay/etc/init.d/S50network
daemon_script=src/buildroot/overlay/etc/init.d/S60equip1d
settings=src/buildroot/overlay/etc/equip1/equip-1.ini
main=src/equip1d/main.py

if grep -q 'dhcp-option="114' "$network_script"; then
  fail "AP DHCP must not advertise a captive portal URL"
fi
if grep -q 'address="/#/' "$network_script"; then
  fail "AP DNS must not wildcard-hijack all domains to the dashboard"
fi
grep -q 'captive_enabled = false' "$settings" || fail "default INI must disable captive portal"
grep -q 'EQUIP1_CAPTIVE_ENABLED network captive_enabled 0' "$daemon_script" || fail "init script must default captive portal off"
grep -q '"network", "captive_enabled", False' "$main" || fail "daemon must default captive portal off"

echo "ok - captive portal triggers are disabled by default"
