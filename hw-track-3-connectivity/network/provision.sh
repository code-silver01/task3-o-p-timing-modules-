#!/bin/bash
# Chronis HW-3 — Network Hardening Provisioning Script
# Run ONCE on a fresh board (Radxa Zero 3W, Ubuntu/Debian-based).
# Idempotent: safe to re-run.
set -euo pipefail

echo "=== Chronis network hardening ==="

# ---------- 1. Firewall (ufw) ----------
apt-get install -y ufw >/dev/null 2>&1 || true
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp     comment 'SSH (key-only)'
ufw allow 443/tcp    comment 'HTTPS sync to cloud gateway'
# BLE is not IP — no firewall rule needed. WiFi sync uses 443 only.
ufw --force enable
echo "[ok] firewall: deny-all inbound except 22, 443"

# ---------- 2. SSH: key-only authentication ----------
SSHD=/etc/ssh/sshd_config
cp "$SSHD" "$SSHD.bak.$(date +%s)"
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "$SSHD"
sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' "$SSHD"
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' "$SSHD"
sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' "$SSHD"
grep -q '^MaxAuthTries' "$SSHD" || echo 'MaxAuthTries 3' >> "$SSHD"
systemctl reload sshd 2>/dev/null || systemctl reload ssh
echo "[ok] SSH: password login disabled, key-only"

# ---------- 3. Verify ----------
ufw status verbose
sshd -T 2>/dev/null | grep -E 'passwordauthentication|pubkeyauthentication' || true
echo "=== hardening complete ==="
