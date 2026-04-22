#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="$HOME/shortlist-backups"
mkdir -p "$BACKUP_DIR"

FILENAME="shortlist_$(date +%Y%m%d_%H%M%S).sql.gz"
DEST="$BACKUP_DIR/$FILENAME"

echo "Backing up to $DEST ..."
docker compose exec -T postgres pg_dump -U copilot job_copilot | gzip > "$DEST"
echo "Backup complete: $DEST"

# Keep only the 30 most recent backups
ls -1t "$BACKUP_DIR"/shortlist_*.sql.gz | tail -n +31 | xargs -r rm --
echo "Old backups pruned (keeping 30 most recent)."
