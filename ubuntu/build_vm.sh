#!/bin/bash
# build_vm.sh - NAT networking

RUN_PRG=$(command -v flatpak-spawn || "")
if [[ $RUN_PRG =~ /flatpak-spawn$ ]]; then
    echo "Working on container..."
    RUN_PRG="$RUN_PRG --host"
fi

export GOLDEN_DISK="/var/lib/libvirt/images/maas-golden.qcow2"
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
    export CLONE_DISK="/var/lib/libvirt/images/${VM_NAME}.qcow2"
    CLONE_CLOUDINIT="/var/lib/libvirt/images/${CLOUDINIT_NAME}.iso"
    echo "📦 Copying golden image..."
    su egb2 -c 'cp -f "$(basename "$GOLDEN_DISK")" "$CLONE_DISK"'
fi

{
	$RUN_PRG virsh --connect qemu:///system undefine maas-dev --nvram
	$RUN_PRG virsh --connect qemu:///system destroy maas-dev
} &>/dev/null

echo "🚀 Creating VM from golden image..."
$RUN_PRG virt-install \
    --connect=qemu:///system \
    --name maas-dev \
    --memory 4096 \
    --vcpus 4 \
    --disk path=/var/lib/libvirt/images/maas-golden.qcow2,format=qcow2 \
    --cdrom /var/lib/libvirt/images/cloud-init.iso \
    --import \
    --os-variant ubuntunoble \
    --boot loader=/usr/share/edk2/ovmf/OVMF_CODE.fd,loader_ro=yes,loader_type=pflash \
    --graphics vnc,password=1234 \
    --check all=off \
    --network network=default \
    --virt-type kvm \
    --autoconsole graphical

echo "✅ VM created: $VM_NAME"
echo ""
echo "📡 VM Network (NAT):"
echo "🔌 To SSH into VM, add port forwarding to qemu command"
echo "   Or use: virsh --connect=qemu:///session console $VM_NAME"
