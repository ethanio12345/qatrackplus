#!/bin/bash
# One-time fix: remount the oncology_d share with write access for bchcphysics.
# Run with: sudo bash /home/bchcphysics/Github/qatrackplus/fix_network_mount.sh

set -euo pipefail

echo "=== Fixing network mount permissions ==="

# Backup the fstab
cp /etc/fstab /etc/fstab.bak.$(date +%Y%m%d)

# Replace the oncology_d line with uid/gid for bchcphysics
sed -i 's|//10.144.30.86/D /mnt/oncology_d cifs.*|//10.144.30.86/D /mnt/oncology_d cifs domain=ONCOLOGY,username=varis,password=varis1,uid=1000,gid=1000,file_mode=0775,dir_mode=0775 0 0|' /etc/fstab

echo "Updated /etc/fstab:"
grep oncology_d /etc/fstab

echo ""
echo "Remounting..."
umount /mnt/oncology_d
mount /mnt/oncology_d

echo ""
echo "Testing write access..."
mkdir -p "/mnt/oncology_d/Physics Data/4. Software/QATrackPlus/Backups/.test"
touch "/mnt/oncology_d/Physics Data/4. Software/QATrackPlus/Backups/.test/write_test"
rm "/mnt/oncology_d/Physics Data/4. Software/QATrackPlus/Backups/.test/write_test"
rmdir "/mnt/oncology_d/Physics Data/4. Software/QATrackPlus/Backups/.test"
echo "Write access: OK"

echo ""
echo "=== Done ==="
