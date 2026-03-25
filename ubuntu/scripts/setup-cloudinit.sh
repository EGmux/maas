#!/bin/bash
# scripts/setup-cloudinit.sh

# Force cloud-init to always check NoCloud datasource
cat > /etc/cloud/cloud.cfg.d/100-force-nocloud.cfg << 'EOF'
datasource_list: [ NoCloud, None ]
datasource:
  NoCloud:
    fs_label: cidata
    seedfrom: file:///run/cloud-init/seed/
EOF

chmod 444 /etc/cloud/cloud.cfg.d/100-force-nocloud.cfg

# Ensure per-boot scripts are enabled
grep -q scripts-per-boot /etc/cloud/cloud.cfg || echo "  - scripts-per-boot" >> /etc/cloud/cloud.cfg
