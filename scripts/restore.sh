#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <backup-file.sql.gz>"
    exit 1
fi

BACKUP_FILE="$1"

if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Error: file not found: $BACKUP_FILE"
    exit 1
fi

echo "WARNING: This will overwrite the current job_copilot database."
echo "Backup file: $BACKUP_FILE"
read -r -p "Type 'yes' to confirm: " CONFIRM

if [[ "$CONFIRM" != "yes" ]]; then
    echo "Aborted."
    exit 1
fi

echo "Restoring from $BACKUP_FILE ..."
gunzip -c "$BACKUP_FILE" | docker compose exec -T postgres psql -U copilot job_copilot
echo "Restore complete."
