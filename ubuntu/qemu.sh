#!/bin/bash
exec flatpak-spawn --host /usr/bin/qemu-system-x86_64 "$@"
