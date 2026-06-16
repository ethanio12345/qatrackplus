#!/bin/bash
# Setup QATrack+ django-q cluster as a systemd service
# Run: sudo bash setup_qcluster_service.sh

SERVICE_NAME="qatrack-qcluster"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

cat > "$SERVICE_FILE" << 'SERVICEEOF'
[Unit]
Description=QATrack+ django-q Cluster
Documentation=https://qatrackplus.com
After=network.target apache2.service

[Service]
Type=simple
User=bchcphysics
Group=bchcphysics
WorkingDirectory=/home/bchcphysics/web/qatrackplus
ExecStart=/home/bchcphysics/web/qatrackplus/.venv/bin/python manage.py qcluster
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl start "$SERVICE_NAME"
systemctl status "$SERVICE_NAME" --no-pager

echo ""
echo "Done. Check status above or run: systemctl status $SERVICE_NAME"
