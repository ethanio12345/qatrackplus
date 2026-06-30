#!/bin/bash
set -euo pipefail

# QATrack+ PostgreSQL rolling backup script.
# Grandfather-Father-Son rotation:
#   Daily:   keep 28 (4 weeks — recover recently lost files)
#   Weekly:  keep 4  (1 month — end-of-week snapshot)
#   Monthly: keep 12 (1 year — retrieve files from earlier in the year)
#   Yearly:  unlimited (never deleted — long-term archive)
#
# Run daily via cron at 3 AM:
#   0 3 * * * /home/bchcphysics/web/qatrackplus/backup.sh
#
# Or run manually: bash /home/bchcphysics/web/qatrackplus/backup.sh

DB_NAME="qatrackplus31"
DB_USER="postgres"
LOCAL_DIR="/home/bchcphysics/web/qatrackplus/backups"
NETWORK_DIR="/mnt/oncology_d/Physics Data/4. Software/QATrackPlus/Backups"

# Retention counts (yearly = unlimited, never pruned)
KEEP_DAILY=28    # 4 weeks
KEEP_WEEKLY=4    # 1 month
KEEP_MONTHLY=12  # 1 year

TIMESTAMP=$(date +"%Y-%m-%d")
DOW=$(date +%u)   # 1=Monday ... 7=Sunday
DOM=$(date +%-d)  # 1-31
MONTH=$(date +"%Y-%m")
QUARTER=$(date +"Y%Y-Q$(( ($(date +%-m) - 1) / 3 + 1 ))")

mkdir -p "$LOCAL_DIR"

# ── Determine backup types for today ────────────────────────────────────────

TYPES=()
TYPES+=("daily")

# Weekly: every Sunday
if [ "$DOW" = "7" ]; then
    TYPES+=("weekly")
fi

# Monthly: 1st of the month
if [ "$DOM" = "1" ]; then
    TYPES+=("monthly")
fi

# Yearly: January 1st only (never pruned)
if [ "$DOM" = "1" ] && [ "$(date +%-m)" = "1" ]; then
    TYPES+=("yearly")
fi

echo "=== QATrack+ Backup — $(date) ==="
echo "Types: ${TYPES[*]}"
echo ""

# ── Create backups ──────────────────────────────────────────────────────────

for TYPE in "${TYPES[@]}"; do
    DIR_NAME="${TIMESTAMP}-${TYPE}"
    LOCAL_PATH="${LOCAL_DIR}/${DIR_NAME}"
    FILE="${LOCAL_PATH}/${DB_NAME}.dump"

    echo "[${TYPE}] Creating backup..."
    mkdir -p "$LOCAL_PATH"

    # pg_dump in custom format (supports parallel restore + compression)
    pg_dump -U "$DB_USER" -Fc -Z6 -f "$FILE" "$DB_NAME" 2>&1

    SIZE=$(du -h "$FILE" | cut -f1)
    echo "    Local: ${FILE} (${SIZE})"

    # Copy to network drive
    if [ -d "$NETWORK_DIR" ]; then
        NET_PATH="${NETWORK_DIR}/${DIR_NAME}"
        mkdir -p "$NET_PATH"
        cp "$FILE" "${NET_PATH}/${DB_NAME}.dump"
        echo "    Network: ${NET_PATH}/${DB_NAME}.dump"
    else
        echo "    WARNING: Network drive not mounted at ${NETWORK_DIR}"
    fi

    echo ""
done

# ── Prune old backups (daily/weekly/monthly only — never yearly) ─────────────

prune_type() {
    local type_name="$1"
    local keep="$2"
    local search_dir="$3"

    echo "[prune] ${type_name}: keeping last ${keep}"

    # List matching dirs sorted newest-first, skip the first ${keep}, delete the rest
    local count=0
    while IFS= read -r dir; do
        count=$((count + 1))
        if [ "$count" -le "$keep" ]; then
            continue
        fi
        echo "    Deleting: $(basename "$dir")"
        rm -rf "$dir"
    done < <(ls -d "${search_dir}"/*-"${type_name}" 2>/dev/null | sort -r)
}

echo "[prune] Cleaning old backups..."
prune_type "daily" "$KEEP_DAILY" "$LOCAL_DIR"
prune_type "weekly" "$KEEP_WEEKLY" "$LOCAL_DIR"
prune_type "monthly" "$KEEP_MONTHLY" "$LOCAL_DIR"

if [ -d "$NETWORK_DIR" ]; then
    prune_type "daily" "$KEEP_DAILY" "$NETWORK_DIR"
    prune_type "weekly" "$KEEP_WEEKLY" "$NETWORK_DIR"
    prune_type "monthly" "$KEEP_MONTHLY" "$NETWORK_DIR"
fi

echo ""

# ── Summary ─────────────────────────────────────────────────────────────────

echo "=== Backup Summary ==="
echo "Local backups:"
ls -1 "$LOCAL_DIR" | sort -r | head -20
echo ""

if [ -d "$NETWORK_DIR" ]; then
    echo "Network backups (most recent):"
    ls -1 "$NETWORK_DIR" | sort -r | head -20
    echo ""
    echo "Network disk usage:"
    du -sh "$NETWORK_DIR"
fi

echo ""
echo "=== Done ==="
