#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PAY="${ROOT}/payload"

rm -rf "$PAY"
mkdir -p "$PAY"

# NetUI, web root, nginx site
[ -d /opt/fakecam-netui ] && mkdir -p "$PAY/opt" && cp -a /opt/fakecam-netui "$PAY/opt/"
[ -d /var/www/html ]      && mkdir -p "$PAY/var/www" && cp -a /var/www/html "$PAY/var/www/"
[ -f /etc/nginx/sites-available/fakecam ] && mkdir -p "$PAY/etc/nginx/sites-available" && cp -a /etc/nginx/sites-available/fakecam "$PAY/etc/nginx/sites-available/"

# MediaMTX e configurazioni
[ -f /etc/mediamtx.yml ] && mkdir -p "$PAY/etc" && cp -a /etc/mediamtx.yml "$PAY/etc/"

# Script e service
mkdir -p "$PAY/usr/local/bin" "$PAY/etc/systemd/system" "$PAY/etc/fakecam/presets.d"
[ -f /usr/local/bin/fakecam-publish.sh ]  && cp -a /usr/local/bin/fakecam-publish.sh  "$PAY/usr/local/bin/"
[ -f /usr/local/bin/fakecam-overlayd.sh ] && cp -a /usr/local/bin/fakecam-overlayd.sh "$PAY/usr/local/bin/"
for svc in fakecam.service fakecam-overlayd.service mediamtx.service; do
  [ -f "/etc/systemd/system/$svc" ] && cp -a "/etc/systemd/system/$svc" "$PAY/etc/systemd/system/"
done

# Config fakecam (overlay, preset, default)
[ -d /etc/fakecam ] && cp -a /etc/fakecam "$PAY/etc/" || mkdir -p "$PAY/etc/fakecam"

echo "Payload aggiornato in: $PAY"
