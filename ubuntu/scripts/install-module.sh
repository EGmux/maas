#!/bin/bash -ex
# install-module.sh - Install custom cloud-init module

# Install Python module
cp /tmp/cc_maas_provision.py /usr/lib/python3/dist-packages/cloudinit/config/
chmod 644 /usr/lib/python3/dist-packages/cloudinit/config/cc_maas_provision.py

# Install config
cp /tmp/99_maas_provision.cfg /etc/cloud/cloud.cfg.d/
chmod 644 /etc/cloud/cloud.cfg.d/99_maas_provision.cfg

echo "✅ Custom cloud-init module installed"
