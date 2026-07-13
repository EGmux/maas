#!/bin/bash
# deploy-multiboot.sh — Automated multi-boot deployment workflow
#
# Usage:
#   ./deploy-multiboot.sh                    # uses /work/layout.yaml
#   ./deploy-multiboot.sh /path/to/layout.yaml
#
# Prerequisites:
#   - maas CLI logged in: maas login admin <url> <api-key>
#   - Profile name "admin" (override with MAAS_PROFILE env var)
#   - Layout file at /work/layout.yaml (or pass as argument)

set -euo pipefail

PROFILE="${MAAS_PROFILE:-admin}"
LAYOUT_FILE="${1:-/home/ubuntu/layout2.yaml}"

# ── Step 0: Verify prereqs ──────────────────────────────────────────
if ! maas "$PROFILE" machines read >/dev/null 2>&1; then
    echo "❌ Not logged into MAAS. Run: maas login $PROFILE <url> <api-key>"
    exit 1
fi

if [[ ! -f "$LAYOUT_FILE" ]]; then
    echo "❌ Layout file not found: $LAYOUT_FILE"
    exit 1
fi

# ── Step 1: List commissioned (Ready) machines ──────────────────────
echo ""
echo "📋 Fetching commissioned machines..."
MACHINES_JSON=$(maas "$PROFILE" machines read 2>/dev/null)

MACHINES=$(echo "$MACHINES_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
ready = [m for m in data if m.get('status_name') == 'Ready']
if not ready:
    print('NONE')
    sys.exit(0)
for i, m in enumerate(ready):
    hostname = m.get('hostname', 'unknown')
    sys_id = m.get('system_id', '???')
    arch = m.get('architecture', '')
    print(f'{i+1}. {hostname:<20} {sys_id:<10} {arch}')
")

if [[ "$MACHINES" == "NONE" ]]; then
    echo "❌ No commissioned (Ready) machines found."
    exit 1
fi

echo "$MACHINES"
echo ""

# ── Step 2: User selection ──────────────────────────────────────────
COUNT=$(echo "$MACHINES" | wc -l | tr -d ' ')
read -r -p "Select machine [1-$COUNT]: " SELECTION

SYSTEM_ID=$(echo "$MACHINES_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
ready = [m for m in data if m.get('status_name') == 'Ready']
try:
    idx = int($SELECTION) - 1
    print(ready[idx]['system_id'])
except (IndexError, ValueError):
    print('ERROR', file=sys.stderr)
    sys.exit(1)
")

if [[ -z "$SYSTEM_ID" ]]; then
    echo "❌ Invalid selection."
    exit 1
fi

echo "✅ Selected: $SYSTEM_ID ($(echo "$MACHINES" | sed -n "${SELECTION}p" | awk '{print $2}'))"

# ── Step 3: Remove any existing layout ──────────────────────────────
echo ""
echo "🗑️  Removing existing layout (if any)..."
maas "$PROFILE" machine delete-layout "$SYSTEM_ID" >/dev/null 2>&1 || true

# ── Step 4: Upload layout ───────────────────────────────────────────
echo ""
echo "📤 Uploading layout from $LAYOUT_FILE ..."
maas "$PROFILE" machine set-layout "$SYSTEM_ID" \
    layout@="$LAYOUT_FILE" >/dev/null

echo "✅ Layout uploaded."

# ── Step 4: Verify layout ───────────────────────────────────────────
echo ""
echo "🔍 Verifying layout..."
maas "$PROFILE" machine get-layout "$SYSTEM_ID"

echo ""
echo "✅ Layout verified."

# ── Step 5: Deploy ──────────────────────────────────────────────────
echo ""
echo "🚀 Deploying multi-boot..."
maas "$PROFILE" machine multi-boot-deploy "$SYSTEM_ID"

echo ""
echo "✅ Deploy triggered for $SYSTEM_ID"

