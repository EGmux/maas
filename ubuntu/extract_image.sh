#!/bin/bash
# convert-to-kvm.sh - WITH PROGRESS!
RUN_PRG=$(command -v flatpak-spawn || "")
# For container based workflows, like Fedora Silverblue
if [[ $RUN_PRG =~ /flatpak-spawn$ ]]; then
	echo "Working on container..."
	echo "using flatpak-spawn"
	RUN_PRG="$RUN_PRG --host"
else
	echo "Working outside of container..."
fi



if [[ ! -f maas-golden.dd  ]]; then
	echo "📦 Decompressing golden image..."
	pv maas-controller-lvm.dd.gz | gunzip > maas-golden.dd
fi

if [[ ! -f maas-golden.qcow2   ]]; then
	echo "🔄 Converting to QCOW2..."
	$RUN_PRG qemu-img convert -f raw -O qcow2 maas-golden.dd maas-golden.qcow2
	echo "✅ Done! KVM image ready: maas-golden.qcow2"
else
	echo "Image already built"
fi


