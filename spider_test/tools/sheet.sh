#!/usr/bin/env bash
# Contact sheet from a frame directory, for LOOKING AT.
#
# Deletes nothing -- but warns about stray files, because a partial render leaves
# stale frames that a glob will happily tile in next to fresh ones, producing a
# sheet that contradicts the code and sends you debugging a bug that is not there.
#
#   sheet.sh out/frames sheet.png 6 2
set -euo pipefail

DIR="${1:-out/frames}"
OUT="${2:-out/sheet.png}"
COLS="${3:-6}"
ROWS="${4:-2}"

shopt -s nullglob
strays=("$DIR"/*\ *.png)
if [ ${#strays[@]} -gt 0 ]; then
  echo "WARNING: ${#strays[@]} stray/duplicate files in $DIR (e.g. $(basename "${strays[0]}"))." >&2
  echo "         Delete them or the sheet will not match the render." >&2
fi

n=$((COLS * ROWS))
files=("$DIR"/f[0-9]*.png)
total=${#files[@]}
[ "$total" -eq 0 ] && { echo "no frames in $DIR" >&2; exit 1; }

mkdir -p "$(dirname "$OUT")"

if [ "$total" -le "$n" ]; then
  ffmpeg -y -loglevel error -pattern_type glob -i "$DIR/f[0-9]*.png" \
    -filter_complex "scale=300:-1,tile=${COLS}x${ROWS}:padding=5:color=0x303030" \
    -frames:v 1 "$OUT"
else
  step=$((total / n))
  [ "$step" -lt 1 ] && step=1
  ffmpeg -y -loglevel error -pattern_type glob -i "$DIR/f[0-9]*.png" \
    -vf "select='not(mod(n\,${step}))',scale=300:-1,tile=${COLS}x${ROWS}:padding=5:color=0x303030" \
    -frames:v 1 -vsync 0 "$OUT"
fi

echo "$OUT  ($total frames, ${COLS}x${ROWS} tiles)"
echo "Now READ it. Defects that are invisible in source are obvious here."
