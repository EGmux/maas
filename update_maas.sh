#!/usr/bin/env bash
set -e

# Configuration
DB_SOCKET_DIR="/var/snap/maas-test-db/common/postgres/sockets"
DUMP_FILE="maasdb.dump"
SNAP_DUMP_PATH="/var/snap/maas-test-db/common/$DUMP_FILE"
DB_NAME="maassampledata"
MAAS_URL="http://localhost:5240/MAAS/"
ADMIN_USER="admin"
ADMIN_PASS="adminpassword123"
ADMIN_EMAIL="admin@example.com"

echo "=== 1. Stopping MAAS snap services ==="
sudo snap stop maas

echo "=== 2. Cleaning up the database namespace ==="
sudo snap run --shell maas-test-db.psql -c "psql -U postgres -h $DB_SOCKET_DIR -d postgres -c 'DROP DATABASE IF EXISTS $DB_NAME;'"

echo "=== 3. Restoring the sample data dump using the test DB snap wrapper ==="
if [ ! -f "$DUMP_FILE" ]; then
    echo "ERROR: $DUMP_FILE not found in the current directory! Run 'make dumpdb DB_DUMP=$DUMP_FILE' first."
    exit 1
fi
sudo cp "$DUMP_FILE" "$SNAP_DUMP_PATH"
sudo snap run --shell maas-test-db.psql -c "db-dump restore \$SNAP_COMMON/$DUMP_FILE $DB_NAME"

echo "=== 4. Granting PostgreSQL schema ownership and privileges to the 'maas' role ==="
sudo snap run --shell maas-test-db.psql -c "psql -U postgres -h $DB_SOCKET_DIR -d $DB_NAME -c 'ALTER SCHEMA public OWNER TO maas; GRANT ALL ON SCHEMA public TO maas;'"

echo "=== 5. Running migrations inside the MAAS Pebble context ==="
sudo snap run --shell maas.pebble -c "maas-region dbupgrade"

echo "=== 6. Creating the administrator account non-interactively ==="
sudo snap run --shell maas.pebble -c "maas-region createadmin --username=$ADMIN_USER --password=$ADMIN_PASS --email=$ADMIN_EMAIL"

echo "=== 7. Syncing dev-snap tree and starting MAAS ==="
##make snap-tree-sync
sudo snap start maas

echo "=== 8. Waiting for the MAAS API server to wake up... ==="
# Loop until port 5240 responds
until curl -s -o /dev/null "$MAAS_URL"; do
    printf '.'
    sleep 2
done
echo " Online!"

echo "=== 9. Authenticating with the MAAS CLI ==="
API_KEY=$(sudo snap run --shell maas.pebble -c "maas-region apikey --user=$ADMIN_USER")
maas login "$ADMIN_USER" "$MAAS_URL" "$API_KEY"

echo "=== 10. Verification: Reading sample machines with jq ==="
echo -e "\nHOSTNAME\t\tSYSTEM_ID\t\tPOWER_TYPE\tSTATUS"
echo "----------------------------------------------------------------------"
maas "$ADMIN_USER" machines read | jq -r '.[] | [.hostname, .system_id, .power_type, .status_name] | @tsv'
