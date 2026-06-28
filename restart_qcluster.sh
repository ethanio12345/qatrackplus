#!/bin/bash
# Kill all stale qcluster processes and restart the service cleanly.
# Run: bash restart_qcluster.sh

PROD="/home/bchcphysics/web/qatrackplus"

echo "=== QATrack+ qcluster Restart ==="
echo ""

# Show current state
echo "[Before]"
ps aux | grep qcluster | grep -v grep | awk '{printf "  %-8s PID=%-8s started=%-10s\n", $1, $2, $9}'
echo ""

# Stop the systemd service first (clean shutdown)
echo "[1] Stopping qatrack-qcluster service..."
sudo systemctl stop qatrack-qcluster
sleep 2

# Kill any remaining processes (old workers from deleted venv)
echo "[2] Killing remaining qcluster processes..."
REMAINING=$(ps aux | grep qcluster | grep -v grep | awk '{print $2}')
if [ -n "$REMAINING" ]; then
    echo "  Stale PIDs: $REMAINING"
    sudo pkill -9 -f "manage.py qcluster" 2>/dev/null || true
    sleep 2
    echo "  Killed."
else
    echo "  None remaining."
fi

# Verify all dead
STILL=$(ps aux | grep qcluster | grep -v grep | wc -l)
if [ "$STILL" -gt 0 ]; then
    echo "  WARNING: $STILL processes still alive:"
    ps aux | grep qcluster | grep -v grep
else
    echo "  All qcluster processes stopped."
fi

# Restart the service
echo ""
echo "[3] Starting qatrack-qcluster service..."
sudo systemctl start qatrack-qcluster
sleep 3

# Verify
echo ""
echo "[After]"
ps aux | grep qcluster | grep -v grep | awk '{printf "  %-8s PID=%-8s started=%-10s\n", $1, $2, $9}'
echo ""
echo "=== Done ==="
echo "Service status:"
sudo systemctl status qatrack-qcluster --no-pager -l 2>&1 | head -15
