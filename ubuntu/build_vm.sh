#!/bin/bash
# build_vm.sh - NAT networking

RUN_PRG=$(command -v flatpak-spawn || "")
if [[ $RUN_PRG =~ /flatpak-spawn$ ]]; then
    echo "Working on container..."
    RUN_PRG="$RUN_PRG --host"
fi

GOLDEN_DISK="$HOME/.local/share/libvirt/images/maas-golden.qcow2"
VM_NAME="maas-dev"
CLOUDINIT_NAME="cloud-init"

if [[ ! -f "$GOLDEN_DISK" ]]; then
    echo "❌ Golden image not found: $GOLDEN_DISK"
    exit 1
fi

CLONE_DISK="$HOME/.local/share/libvirt/images/${VM_NAME}.qcow2"
CLONE_CLOUDINIT="$HOME/.local/share/libvirt/images/${CLOUDINIT_NAME}.iso"
echo "📦 Cloning golden image..."
cp "$GOLDEN_DISK" "$CLONE_DISK"
cp "${CLOUDINIT_NAME}.iso" "$CLONE_CLOUDINIT"

echo "🚀 Creating VM from golden image..."
$RUN_PRG virt-install \
    --connect=qemu:///session \
    --name maas-dev \
    --memory 4096 \
    --vcpus 4 \
    --disk path=/var/home/egb2/.local/share/libvirt/images/maas-dev.qcow2,format=qcow2 \
    --cdrom /var/home/egb2/.local/share/libvirt/images/cloud-init.iso \
    --import \
    --os-variant ubuntunoble \
    --boot loader=/usr/share/edk2/ovmf/OVMF_CODE.fd,loader_ro=yes,loader_type=pflash \
    --graphics vnc,password=1234 \
    --network user,model=virtio \
    --virt-type kvm \
    --autoconsole graphical

echo "✅ VM created: $VM_NAME"
echo ""
echo "📡 VM Network (NAT):"
echo "   VM gets IP: 10.0.2.15 (via DHCP)"
echo "   Internet: works through host"
echo ""
echo "🔌 To SSH into VM, add port forwarding to qemu command"
echo "   Or use: virsh --connect=qemu:///session console $VM_NAME"
