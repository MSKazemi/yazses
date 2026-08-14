#!/bin/bash
# Does this application receive dictated text unchanged?
#
#   docker build -t yazses-appprobe scripts/appprobe
#   docker run --rm -v "$PWD/scripts/appprobe:/work" yazses-appprobe \
#       bash /work/probe.sh kitty "" "" kitty bash -c 'cat > /work/out.txt'
#
# WHY THIS EXISTS. An `examples/config.<app>.toml` is supposed to be tested, and
# the issues asking for one rightly refuse a config nobody ran. But the part that
# actually differs between applications is not the speech — it is whether the
# text survives arriving. This drives the SAME xdotool XTEST path the daemon
# uses, which an application cannot distinguish from a real keypress, on an
# isolated virtual display that cannot touch your desktop.
#
# It does NOT test dictation. Say so in your pull request, as the shipped configs
# do — half a measurement honestly labelled beats a whole one asserted.
#
# Usage: probe.sh LABEL PRE_KEYS POST_KEYS -- command to launch the app
#   PRE_KEYS   xdotool keys to send before typing (e.g. `i` for Neovim insert)
#   POST_KEYS  keys to send after (e.g. "Escape colon w Return colon q Return")
set -u
LABEL="$1"; PRE="$2"; POST="$3"; shift 3
OUT=/work/out.txt
rm -f "$OUT"; : > "$OUT"
export DISPLAY=:99
pkill -f "Xvfb :99" 2>/dev/null; sleep 1
Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1 &
sleep 2
# A window manager is required: without one nothing holds focus, and xdotool
# falls back to XSendEvent, which most applications ignore for security.
openbox >/dev/null 2>&1 &
sleep 2
"$@" >/dev/null 2>&1 &
sleep 7

WIN=$(xdotool search --onlyvisible --class . 2>/dev/null | tail -1)
[ -z "$WIN" ] && { echo "RESULT|$LABEL|NO_WINDOW|"; exit 0; }
xdotool windowactivate --sync "$WIN" 2>/dev/null; sleep 1

# Flags, an operator and a path: the things applications mangle.
TEXT='kubectl get pods --namespace prod && cat src/main.py'
[ -n "$PRE" ] && { xdotool key $PRE; sleep 1; }
xdotool type --delay 6 "$TEXT"
sleep 1
if [ -n "$POST" ]; then for k in $POST; do xdotool key "$k"; sleep 0.6; done
else xdotool key Return; fi
sleep 3

GOT=$(tr -d '\000' < "$OUT" 2>/dev/null | head -c 200 | tr '\n' ' ')
if [ "$GOT" = "$TEXT " ] || [ "$GOT" = "$TEXT" ]; then V=EXACT
elif [ -n "$GOT" ]; then V=PARTIAL; else V=NOTHING; fi
echo "RESULT|$LABEL|$V|$GOT"
