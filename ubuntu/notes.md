# NOTES:  Possible way to implement the feature

## Context
- Why does this project exist?
- What problem does it solve?
- Who is it for?

## Commands
- `cmd1` - what it does
- `cmd2` - what it does

## Configs
- `path/to/config` - what it controls

## Quirks
- Things that don't work as expected
- Workarounds
- Gotchas

## TODO
- [ ] 

## Notes

MAAS Dual-Boot Hack: Multipartite Partition Illusion

Problem: MAAS requires full disk ownership → can't dual-boot.

Hack: Use multipath to make one physical disk appear as two virtual "disks" to MAAS.
text

Physical: /dev/sda
├── Partition 1 (200G) → /dev/mapper/maas-disk (MAAS thinks it's a full disk)
└── Partition 2 (200G) → /dev/mapper/windows-disk (Windows partition)

MAAS deploys to maas-disk → actually just partition 1 → Windows gets partition 2 → GRUB boots both

Implementation:
yaml

block-meta:
  devices: [/dev/sda]
  partitions:
    - {name: maas-part, size: 200G, flag: boot}
    - {name: windows-part, size: 200G}
multipath:
  custom_bindings:
    - {wwid: "maas-wwid", device: /dev/sda1}
    - {wwid: "windows-wwid", device: /dev/sda2}

Result: Dual-boot without modifying MAAS core. 🔧

## Scratch

A possible prototype startpoint
---
