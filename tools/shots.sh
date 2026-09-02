#!/usr/bin/env bash
# Capture every surface at both target widths into .impeccable/review/.
#
# Two things this works around, both learned the hard way:
#   - concurrent headless Chromes sharing a profile fail silently, writing no file and
#     printing no error, so each run gets its own --user-data-dir;
#   - Chrome will not lay out below roughly 500 CSS px here. A narrower --window-size crops
#     a wider render instead of reflowing it, which is invalid evidence, not a small one.
set -u

here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
win () { printf '%s' "$1" | sed 's|^/\([a-zA-Z]\)/|\1:/|'; }

ROOT=$(win "$here")
OUT="$ROOT/.impeccable/review"
TMP="${TMPDIR:-/tmp}/mockingbird-shots"
CHROME="${CHROME:-/c/Program Files/Google/Chrome/Application/chrome.exe}"
BASE="${BASE:-http://localhost:8000}"
mkdir -p "$here/.impeccable/review"
n=0

shot () {
  n=$((n + 1))
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --user-data-dir="$(win "$TMP")/$n" --virtual-time-budget="${BUDGET:-7000}" \
    --window-size="$2" --screenshot="$OUT/$1.png" "$BASE$3" 2>&1 |
    grep -iE "ERROR:.*screenshot|written" | tail -1
}

for w in "desktop 1440,1100" "narrow 500,1000"; do
  set -- $w
  shot "plan-$1" "$2" /
  shot "session-$1" "$2" /session
  shot "history-$1" "$2" /history
done
