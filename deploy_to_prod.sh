#!/bin/bash
set -euo pipefail

# Production deployment script for QATrack+ myQA system.
# Run from the dev repo root: bash deploy_to_prod.sh
#
# Usage:
#   bash deploy_to_prod.sh          # full deploy (git pull + uv sync + restart)
#   bash deploy_to_prod.sh --code   # code only (skip venv/restart)
#   bash deploy_to_prod.sh --first  # first-time setup (fixes venv ownership)

PROD="/home/bchcphysics/web/qatrackplus"
DEV="/home/bchcphysics/Github/qatrackplus"
VENV="$PROD/.venv"
MODE="${1:-full}"

echo "=== QATrack+ Production Deployment ==="
echo "Mode: $MODE"
echo "Production: $PROD"
echo ""

# ── Step 0: First-time setup ──────────────────────────────────────────────
if [ "$MODE" = "--first" ]; then
    echo "[0] Recreating venv (root-owned → user-owned)..."
    # The production venv may be owned by root. We can't chown it without
    # sudo, but we CAN rename it (parent dir is user-owned) and create a
    # fresh one. The old venv is cleaned up after uv sync succeeds.
    if [ -d "$VENV" ] && [ ! -w "$VENV/bin" ]; then
        mv "$VENV" "$VENV.old"
        echo "    Old root-owned venv moved to .venv.old"
    fi
    echo ""
fi

# ── Step 1: Fetch latest code ─────────────────────────────────────────────
echo "[1] Fetching latest code from origin/develop..."
cd "$PROD"
git fetch origin
CURRENT=$(git rev-parse --short HEAD)
LATEST=$(git rev-parse --short origin/develop)
echo "    Current: $CURRENT"
echo "    Latest:  $LATEST"

if [ "$CURRENT" = "$LATEST" ] && [ "$MODE" != "--first" ]; then
    echo "    Already up to date."
    echo ""
    echo "=== Done ==="
    exit 0
fi

# ── Step 2: Reset to origin/develop ───────────────────────────────────────
echo ""
echo "[2] Resetting production to origin/develop..."
git stash --include-untracked -q || true
git reset --hard origin/develop
echo "    Reset complete."

# Restore local_settings.py from stash (it's gitignored but stash may have it)
git stash pop -q 2>/dev/null || true

# Clean up old manually-copied files that are now tracked
echo "    Cleaning stale untracked files..."
rm -rf "$PROD/vendor" 2>/dev/null || true
echo "    Done."

# ── Step 3: Install dependencies ──────────────────────────────────────────
if [ "$MODE" != "--code" ]; then
    echo ""
    echo "[3] Installing dependencies (uv sync)..."
    cd "$PROD"
    uv sync 2>&1 | tail -5
    echo "    Dependencies installed."
else
    echo ""
    echo "[3] Skipping dependencies (--code mode)"
fi

# ── Step 4: Verify ────────────────────────────────────────────────────────
echo ""
echo "[4] Verifying..."
cd "$PROD"

# Check pymssql
if $VENV/bin/python -c "import pymssql" 2>/dev/null; then
    echo "    pymssql: OK"
else
    echo "    pymssql: MISSING — run with --first to fix venv, then re-run"
    exit 1
fi

# Django system check
$VENV/bin/python manage.py check 2>&1 | tail -1

# ── Step 5: Restart services ──────────────────────────────────────────────
if [ "$MODE" != "--code" ]; then
    echo ""
    echo "[5] Restarting services..."
    # Try sudo first; if unavailable, kill workers so systemd respawns them.
    if sudo -n true 2>/dev/null; then
        sudo systemctl restart qatrack-qcluster
        sudo systemctl reload apache2 2>/dev/null || true
        echo "    qcluster + apache restarted (via systemctl)."
    else
        pkill -u "$(whoami)" -f "manage.py qcluster" 2>/dev/null || true
        echo "    Killed qcluster workers — systemd will respawn with new code."
        echo "    For www-data workers + apache, run manually:"
        echo "      sudo systemctl restart qatrack-qcluster"
        echo "      sudo systemctl reload apache2"
    fi
else
    echo ""
    echo "[5] Skipping service restart (--code mode)"
    echo "    Restart manually: sudo systemctl restart qatrack-qcluster"
fi

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo "=== Deployment Complete ==="
echo "Commit: $(git rev-parse --short HEAD)"
echo ""
echo "To run the myQA data pipeline:"
echo "  cd $PROD"
echo "  .venv/bin/python manage.py clear_myqa_data --yes"
echo "  .venv/bin/python manage.py setup_myqa_tests"
echo "  .venv/bin/python manage.py import_myqa --days 3650"
