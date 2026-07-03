#!/usr/bin/env bash
set -euo pipefail

VM_NAME="firehat-builder"
VM_IMAGE="ghcr.io/cirruslabs/ubuntu:latest"
DISK_SIZE=50  # GB — Buildroot needs ~30GB for sources + build artifacts

# Build key used by build.sh/clean.sh/vm-ssh.sh. First contact uses the image's
# default password (admin) via expect; after that everything is key-based.
SSH_KEY="$HOME/.ssh/firehat-builder"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i $SSH_KEY"
VM_PASSWORD="${VM_PASSWORD:-admin}"

if [ ! -f "$SSH_KEY" ]; then
    echo "==> Generating build SSH key at $SSH_KEY..."
    ssh-keygen -t ed25519 -N "" -f "$SSH_KEY" -C "firehat-builder" >/dev/null
fi

# Check if VM already exists
if tart list | grep -q "$VM_NAME"; then
    echo "VM '$VM_NAME' already exists."
    echo "To recreate: tart delete $VM_NAME && ./buildroot/scripts/vm-setup.sh"
    exit 0
fi

echo "==> Cloning base image..."
tart clone "$VM_IMAGE" "$VM_NAME"

echo "==> Resizing disk to ${DISK_SIZE}GB..."
tart set "$VM_NAME" --disk-size "$DISK_SIZE"

echo "==> Setting RAM to 8GB..."
tart set "$VM_NAME" --memory 8192

echo "==> Starting VM (headless)..."
tart run --no-graphics "$VM_NAME" &
VM_PID=$!

echo "==> Waiting for VM to boot..."
sleep 15

# Wait for the VM to get an IP and open its SSH port
VM_IP=""
PORT_OK=false
for i in $(seq 1 60); do
    VM_IP=$(tart ip "$VM_NAME" 2>/dev/null || true)
    if [ -n "$VM_IP" ]; then
        if nc -z -G 5 "$VM_IP" 22 2>/dev/null; then
            PORT_OK=true
            break
        fi
    fi
    echo "  waiting for SSH port... ($i/60)"
    sleep 5
done

if [ "$PORT_OK" != "true" ]; then
    echo "ERROR: VM SSH port never opened (IP: ${VM_IP:-none})."
    kill $VM_PID 2>/dev/null || true
    exit 1
fi

echo "==> VM IP: $VM_IP"

# Install the build key into the VM using the default password (one-time).
echo "==> Installing build SSH key into VM..."
PUBKEY="$(cat "$SSH_KEY.pub")"
/usr/bin/expect <<EOF
set timeout 60
spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null admin@$VM_IP "mkdir -p ~/.ssh && chmod 700 ~/.ssh && grep -qxF '$PUBKEY' ~/.ssh/authorized_keys 2>/dev/null || echo '$PUBKEY' >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys"
expect {
    -re "(?i)password:"     { send "$VM_PASSWORD\r"; exp_continue }
    -re "(?i)are you sure"  { send "yes\r"; exp_continue }
    eof
}
EOF

# Verify key-based auth works before provisioning.
if ! ssh $SSH_OPTS -o ConnectTimeout=10 admin@"$VM_IP" true 2>/dev/null; then
    echo "ERROR: Key-based SSH still failing after key install."
    kill $VM_PID 2>/dev/null || true
    exit 1
fi
echo "==> Key-based SSH confirmed."

echo "==> Provisioning build dependencies..."

ssh $SSH_OPTS admin@"$VM_IP" bash <<'PROVISION'
set -euo pipefail

sudo apt-get update
sudo apt-get install -y \
    build-essential \
    git \
    wget \
    cpio \
    unzip \
    rsync \
    bc \
    libncurses-dev \
    file \
    python3 \
    python3-setuptools \
    python3-dev \
    python3-pip \
    python3-venv \
    which \
    libssl-dev \
    device-tree-compiler \
    bison \
    flex \
    swig \
    dosfstools \
    mtools \
    e2fsprogs \
    u-boot-tools \
    libelf-dev \
    libgnutls28-dev \
    libfdt-dev \
    python3-libfdt

echo "==> Cloning Buildroot..."
if [ -d "$HOME/buildroot" ] && ! git -C "$HOME/buildroot" log --oneline -1 &>/dev/null; then
    echo "  Buildroot checkout is broken, removing..."
    rm -rf "$HOME/buildroot"
fi
if [ ! -d "$HOME/buildroot" ]; then
    git clone --branch 2025.02.x https://gitlab.com/buildroot.org/buildroot.git "$HOME/buildroot"
else
    echo "Buildroot already cloned."
fi

echo "==> Cloning rkbin (Rockchip firmware blobs)..."
if [ ! -d "$HOME/rkbin" ]; then
    git clone --depth 1 https://github.com/rockchip-linux/rkbin.git "$HOME/rkbin"
else
    echo "rkbin already cloned."
fi

echo "==> Provisioning complete."
PROVISION

echo ""
echo "==> VM '$VM_NAME' is ready."
echo "    IP: $VM_IP"
echo "    SSH: ssh -i $SSH_KEY admin@$VM_IP   (or ./buildroot/scripts/vm-ssh.sh)"
echo ""
echo "==> Stopping VM. Use './buildroot/scripts/build.sh' to build images."
tart stop "$VM_NAME" 2>/dev/null || true
wait $VM_PID 2>/dev/null || true
