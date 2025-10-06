#!/usr/bin/env bash
set -euo pipefail
LABEL_FILE="/etc/fakecam/overlay.txt"
TS_ON_FILE="/etc/fakecam/timestamp.enabled"
TS_FMT_FILE="/etc/fakecam/timestamp.format"
OUT="/etc/fakecam/overlay_render.txt"

label() { [ -s "$LABEL_FILE" ] && sed -n '1p' "$LABEL_FILE" || echo "CAM01"; }
ts_on() { [ -s "$TS_ON_FILE" ] && grep -qi '^on$' "$TS_ON_FILE" && return 0 || return 1; }
ts_fmt(){ [ -s "$TS_FMT_FILE" ] && sed -n '1p' "$TS_FMT_FILE" || echo '%Y-%m-%d %H:%M:%S'; }

while :; do
  L="$(label)"
  if ts_on; then
    F="$(ts_fmt)"
    NOW="$(date +"$F")"
    echo "$L  $NOW" > "$OUT"
  else
    echo "$L" > "$OUT"
  fi
  sleep 1
done
