#!/usr/bin/env bash
set -euo pipefail
MEDIAMTX_URL="${MEDIAMTX_URL:-https://github.com/bluenviron/mediamtx/releases/download/v1.15.1/mediamtx_v1.15.1_linux_amd64.tar.gz}"
HTTP_PORT="${FAKECAM_HTTP_PORT:-8080}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Se non c'è payload.tgz, crealo da installer/payload/
if [ ! -f payload.tgz ]; then
  if [ -d payload ]; then
    tar -czf payload.tgz -C payload .
  else
    echo "Errore: manca payload/ o payload.tgz" >&2
    exit 1
  fi
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y install nginx python3-venv python3-pip ffmpeg curl ca-certificates fonts-dejavu-core apache2-utils

# MediaMTX
install -d /usr/local/bin
TMP="$(mktemp -d)"
curl -L "$MEDIAMTX_URL" -o "$TMP/mediamtx.tgz"
tar -xzf "$TMP/mediamtx.tgz" -C "$TMP"
[ -f "$TMP/mediamtx" ] && install -m 0755 "$TMP/mediamtx" /usr/local/bin/mediamtx
rm -rf "$TMP"

# Config di base mediamtx (se non presente)
if [ ! -f /etc/mediamtx.yml ]; then
  cat >/etc/mediamtx.yml <<'YAML'
hls: yes
hlsAddress: :8888
rtspAddress: :8554
paths:
  cam1:
YAML
fi

# Srotola payload
tar -xzf payload.tgz -C /

# Nginx site: imposta porta e abilita
if [ -f /etc/nginx/sites-available/fakecam ]; then
  sed -i "s/^\\s*listen\\s\\+[0-9]\\+\\s\\+default_server;/    listen ${HTTP_PORT} default_server;/" /etc/nginx/sites-available/fakecam
  ln -sf /etc/nginx/sites-available/fakecam /etc/nginx/sites-enabled/fakecam
  rm -f /etc/nginx/sites-enabled/default || true
  nginx -t
  systemctl enable --now nginx
fi

# NetUI venv + deps
if [ -d /opt/fakecam-netui ]; then
  python3 -m venv /opt/fakecam-netui/venv
  /opt/fakecam-netui/venv/bin/pip install --upgrade pip
  /opt/fakecam-netui/venv/bin/pip install flask
fi

# Basic auth admin/admin (se manca)
if [ ! -f /etc/nginx/.htpasswd ]; then
  htpasswd -bBc /etc/nginx/.htpasswd admin admin
  systemctl reload nginx || true
fi

# Permessi
chmod +x /usr/local/bin/fakecam-publish.sh /usr/local/bin/fakecam-overlayd.sh 2>/dev/null || true

# Servizi
systemctl daemon-reload
systemctl enable --now mediamtx.service 2>/dev/null || systemctl enable --now mediamtx || true
systemctl enable --now fakecam.service 2>/dev/null || true
systemctl enable --now fakecam-overlayd.service 2>/dev/null || true
systemctl enable --now fakecam-netui.service 2>/dev/null || true
systemctl enable --now systemd-networkd || true

echo
echo "==> Installazione completata."
echo "    NetUI:  http://IP:${HTTP_PORT}/netui/  (admin/admin)"
echo "    HLS:    http://IP:${HTTP_PORT}/hls/cam1/index.m3u8  (autenticazione)"
echo
