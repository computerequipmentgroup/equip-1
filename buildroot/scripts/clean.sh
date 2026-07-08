#!/usr/bin/env bash
set -euo pipefail

VM_NAME="equip1-builder"
SSH_KEY="$HOME/.ssh/equip1-builder"
SSH_OPTS="-o StrictHostKeyChecking=no -i $SSH_KEY"

VM_IP=$(tart ip "$VM_NAME" 2>/dev/null || true)
if [ -z "$VM_IP" ]; then
    echo "ERROR: VM '$VM_NAME' is not running."
    exit 1
fi

echo "==> Cleaning buildroot on VM..."
ssh $SSH_OPTS admin@"$VM_IP" "cd ~/buildroot && rm -rf .config output"
echo "==> Done. Next build will start from scratch."
