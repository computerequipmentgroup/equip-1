#!/usr/bin/env bash
set -euo pipefail

# Create/update a NetworkManager Wi-Fi access point for Firehat.
# Override these in /etc/firehat/ap.env or the systemd unit environment.
if [[ "${FIREHAT_AP_ENABLED:-1}" =~ ^(0|false|False|FALSE|no|No|NO|off|Off|OFF)$ ]]; then
  echo "Firehat AP disabled (FIREHAT_AP_ENABLED=${FIREHAT_AP_ENABLED:-})"
  exit 0
fi

CONNECTION="${FIREHAT_AP_CONNECTION:-firehat-ap}"
IFACE="${FIREHAT_AP_IFACE:-wlan0}"
SSID="${FIREHAT_AP_SSID:-Equip-1}"
PASSWORD="${FIREHAT_AP_PASSWORD:-firesecret}"
IP_CIDR="${FIREHAT_AP_IP:-10.42.0.1/24}"
BAND="${FIREHAT_AP_BAND:-bg}"
CHANNEL="${FIREHAT_AP_CHANNEL:-6}"

if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli is required. Install/enable NetworkManager first." >&2
  exit 1
fi

if [[ ${#PASSWORD} -lt 8 ]]; then
  echo "FIREHAT_AP_PASSWORD must be at least 8 characters for WPA-PSK." >&2
  exit 1
fi

if ! nmcli -g GENERAL.DEVICE device show "$IFACE" >/dev/null 2>&1; then
  echo "Wi-Fi interface '$IFACE' was not found. Set FIREHAT_AP_IFACE in /etc/firehat/ap.env." >&2
  nmcli device status || true
  exit 1
fi

nmcli radio wifi on

if ! nmcli -t -f NAME connection show | grep -Fxq "$CONNECTION"; then
  nmcli connection add \
    type wifi \
    ifname "$IFACE" \
    con-name "$CONNECTION" \
    autoconnect yes \
    ssid "$SSID"
fi

nmcli connection modify "$CONNECTION" \
  connection.interface-name "$IFACE" \
  connection.autoconnect yes \
  connection.autoconnect-priority 100 \
  802-11-wireless.mode ap \
  802-11-wireless.ssid "$SSID" \
  802-11-wireless.band "$BAND" \
  802-11-wireless.channel "$CHANNEL" \
  802-11-wireless-security.key-mgmt wpa-psk \
  802-11-wireless-security.psk "$PASSWORD" \
  ipv4.method shared \
  ipv4.addresses "$IP_CIDR" \
  ipv6.method ignore

nmcli --wait 20 connection up "$CONNECTION" ifname "$IFACE"

echo "Firehat AP '$SSID' is up on $IFACE at $IP_CIDR"
