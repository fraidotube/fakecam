#!/usr/bin/env bash
set -euo pipefail

FONT="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
RENDER_FILE="/etc/fakecam/overlay_render.txt"

SRC_FILE="/etc/fakecam/source.txt"
PAT_FILE="/etc/fakecam/pattern.txt"
COLOR_FILE="/etc/fakecam/color.txt"

SIZE="1280x720"
FPS="25"

# --- sorgente ---
SRC="$( [ -s "$SRC_FILE" ] && sed -n '1p' "$SRC_FILE" || echo "" )"
PATTERN="$(sed -n '1p' "$PAT_FILE" 2>/dev/null || echo testsrc)"
COLOR="$(sed -n '1p' "$COLOR_FILE" 2>/dev/null || echo red)"

declare -a IN_OPTS=()
if [[ -n "$SRC" ]]; then
  lowSRC="$(echo "$SRC" | tr '[:upper:]' '[:lower:]')"
  if [[ "$lowSRC" =~ \.m3u8($|\?) ]]; then
    # HLS remoto → user agent + timeout + reconnect
    IN_OPTS=( -re -user_agent "Mozilla/5.0 (FakeCam)" \
      -rw_timeout 15000000 -timeout 15000000 \
      -reconnect 1 -reconnect_streamed 1 -reconnect_on_network_error 1 \
      -i "$SRC" )
  elif [[ "$lowSRC" =~ ^rtsp:// ]]; then
    # RTSP → preferisci TCP per affidabilità
    IN_OPTS=( -rtsp_transport tcp -re -i "$SRC" )
  elif [[ "$lowSRC" =~ ^https?://.*\.mp4($|\?) ]]; then
    # MP4 via HTTP(S) → loop infinito
    IN_OPTS=( -re -stream_loop -1 -i "$SRC" )
  elif [[ -f "$SRC" ]]; then
    # file locale
    case "$lowSRC" in
      *.mp4|*.mov|*.mkv|*.avi) IN_OPTS=( -re -stream_loop -1 -i "$SRC" );;
      *)                        IN_OPTS=( -re -i "$SRC" ) ;;
    esac
  else
    echo "Sorgente non riconosciuta/irraggiungibile: $SRC" >&2
    exit 1
  fi
else
  case "$PATTERN" in
    testsrc|testsrc2|smptebars|smptehdbars) LAVFI="${PATTERN}=size=${SIZE}:rate=${FPS}" ;;
    color)  LAVFI="color=c=${COLOR}:size=${SIZE}:rate=${FPS}" ;;
    *)      LAVFI="testsrc=size=${SIZE}:rate=${FPS}" ;;
  esac
  IN_OPTS=( -re -f lavfi -i "$LAVFI" )
fi

# --- audio di comodo ---
AUD_OPTS=( -f lavfi -i sine=frequency=1000:sample_rate=48000 )

# --- overlay (unico drawtext con reload del file renderizzato) ---
DRAW="[0:v]drawtext=fontfile=${FONT}:textfile=${RENDER_FILE}:reload=1:x=20:y=20:fontsize=36:fontcolor=white:box=1:boxcolor=0x00000088[v]"

exec ffmpeg -loglevel warning \
  "${IN_OPTS[@]}" "${AUD_OPTS[@]}" \
  -filter_complex "$DRAW" -map "[v]" -map 1:a \
  -use_wallclock_as_timestamps 1 \
  -c:v libx264 -profile:v baseline -level 3.0 -preset veryfast -tune zerolatency -pix_fmt yuv420p -g $((FPS*2)) -r "${FPS}" \
  -c:a aac -ar 48000 -b:a 96k \
  -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam1
