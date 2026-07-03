#!/usr/bin/env bash
set -euo pipefail

VM_NAME="firehat-builder"
SSH_KEY="$HOME/.ssh/firehat-builder"
SSH_OPTS="-o StrictHostKeyChecking=no -i $SSH_KEY"

# Check if VM is running
if ! tart list | grep "$VM_NAME" | grep -q "running"; then
    echo "==> Starting VM..."
    tart run --no-graphics "$VM_NAME" &
    sleep 10
fi

VM_IP=""
for i in $(seq 1 20); do
    VM_IP=$(tart ip "$VM_NAME" 2>/dev/null || true)
    if [ -n "$VM_IP" ]; then
        break
    fi
    sleep 3
done

if [ -z "$VM_IP" ]; then
    echo "ERROR: Could not get VM IP."
    exit 1
fi

echo "==> Connecting to $VM_NAME ($VM_IP)..."
ssh $SSH_OPTS admin@"$VM_IP"
