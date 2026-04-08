#!/bin/bash
# build_vm.sh - NAT networking

RUN_PRG=$(command -v flatpak-spawn || "")
if [[ $RUN_PRG =~ /flatpak-spawn$ ]]; then
    echo "Working on container..."
    RUN_PRG="$RUN_PRG --host"
fi

GOLDEN_DISK="$HOME/.local/share/libvirt/images/maas-golden.qcow2"
VM_NAME="maas-golden"
MODIFY_IMAGE=false

if [[ ! -f "maas-golden.qcow2"  ]]; then
	echo "📦 Golden image not found, extracting..."
	source "extract_image.sh"
fi

if [[ ! -f "maas-golden.qcow2" ]]; then
	echo "Failed to extract golden image, critical error"
	exit 1
fi


if [[ ! -f "$GOLDEN_DISK" ]] ; then
    echo "❌ Golden image not found in $GOLDEN_DISK"
    MODIFY_IMAGE=true
elif ! diff -q "$GOLDEN_DISK" "$PWD/${VM_NAME}.qcow2" &>/dev/null ; then
    echo "❌ Golden image is newer than $GOLDEN_DISK"
    MODIFY_IMAGE=true
fi

if [[  "$MODIFY_IMAGE" == true  ]]; then
    CLONE_DISK="$HOME/.local/share/libvirt/images/${VM_NAME}.qcow2"
    CLONE_CLOUDINIT="$HOME/.local/share/libvirt/images/${CLOUDINIT_NAME}.iso"
    echo "📦 Copying golden image..."
    cp -f "$(basename $GOLDEN_DISK)" "$CLONE_DISK"
fi

{
	$RUN_PRG virsh undefine maas-dev --nvram
	$RUN_PRG virsh destroy maas-dev
} &>/dev/null

echo "🚀 Creating VM from golden image..."
$RUN_PRG virt-install \
    --connect=qemu:///session \
    --name maas-dev \
    --memory 4096 \
    --vcpus 4 \
    --disk path=$HOME/.local/share/libvirt/images/maas-golden.qcow2,format=qcow2 \
    --cdrom $HOME/.local/share/libvirt/images/cloud-init.iso \
    --import \
    --os-variant ubuntunoble \
    --boot loader=/usr/share/OVMF/OVMF_CODE_4M.fd,loader_ro=yes,loader_type=pflash \
    --graphics vnc,password=1234 \
    --qemu-commandline="-netdev user,id=net1,hostfwd=tcp:127.0.0.1:2222-:22,hostfwd=tcp:127.0.0.1:5240-:5240" \
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
