#!/usr/bin/env bash
# ==============================================================================
# SCRIPT: nuke_maas.sh
# DESCRIPTION: Completely purges, unlinks, and wipes MAAS & MAAS_TEST_DB snaps
#              along with all systemd traces, cache folders, and locked sockets.
# AUTHOR: Enzo Gurgel Bissoli
# ==============================================================================

# Ensure the script is run with root privileges
if [ "$EUID" -ne 0 ]; then
  echo "❌ Error: This script must be run as root (sudo)."
  exit 1
fi

echo "========================================================"
echo "💥 INITIALIZING ULTIMATE MAAS PURGE SEQUENCE 💥"
echo "========================================================"

# ------------------------------------------------------------------------------
# STEP 1: FORCE SYSTEMD TO RELEASE SERVICE HANDLES
# ------------------------------------------------------------------------------
echo "⏳ Stopping and disabling systemd service units..."
systemctl stop snap.maas.pebble.service 2>/dev/null
systemctl disable snap.maas.pebble.service 2>/dev/null
systemctl stop snap.maas-test-db.*.service 2>/dev/null
systemctl disable snap.maas-test-db.*.service 2>/dev/null

# ------------------------------------------------------------------------------
# STEP 2: NUKE RUNAWAY/STUCK PROCESSES FROM KERNEL MEMORY
# ------------------------------------------------------------------------------
echo "⚔️ Hunting down zombie processes (pebble, postgres, maas)..."
killall -9 pebble postgres maas 2>/dev/null
sleep 2

# ------------------------------------------------------------------------------
# STEP 3: PURGE SNAPS VIA SNAPD (NO BACKUPS ALLOWED)
# ------------------------------------------------------------------------------
echo "🗑️ Executing deep snap purge for 'maas'..."
snap remove --purge maas

echo "🗑️ Executing deep snap purge for 'maas-test-db'..."
snap remove --purge maas-test-db

# ------------------------------------------------------------------------------
# STEP 4: MANUAL FILESYSTEM SANITIZATION (WIPING GHOST TRACKS)
# ------------------------------------------------------------------------------
echo "🧹 Erasing core configuration and database host directories..."
rm -rf /var/snap/maas/
rm -rf /var/snap/maas-test-db/

echo "🧹 Clearing user-space snap configs (Ubuntu & Root)..."
rm -rf /home/ubuntu/snap/maas/
rm -rf /home/ubuntu/snap/maas-test-db/
rm -rf /root/snap/maas/
rm -rf /root/snap/maas-test-db/

echo "🧹 Cleaning cached mount spaces..."
rm -rf /var/lib/snapd/snap/maas/
rm -rf /var/lib/snapd/snap/maas-test-db/

# ------------------------------------------------------------------------------
# STEP 5: RESET SYSTEMD DAEMON MATRIX
# ------------------------------------------------------------------------------
echo "🔄 Reloading systemd manager to clear dead socket configurations..."
systemctl daemon-reload
systemctl reset-failed

echo "========================================================"
echo "✨ CLEAN SLATE ACHIEVED SUCCESSFULLY! ✨"
echo "========================================================"
echo "Remaining Snap Status:"
snap list | grep -E "maas|pebble" || echo "✅ No MAAS or Pebble trace elements found."

