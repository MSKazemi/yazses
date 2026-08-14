#!/bin/bash
# Does this GUI application receive dictated text unchanged? (Electron / Gecko)
#
#   docker build -f scripts/appprobe/Dockerfile.gui -t yazses-appprobe-gui scripts/appprobe
#   docker run --rm --shm-size=2g -v "$PWD/scripts/appprobe:/work" yazses-appprobe-gui \
#       bash /work/probe-gui.sh firefox 50 50 /opt/firefox/firefox \
#            --no-remote --profile /tmp/ffp file:///work/page.html
#
# WHY THIS IS A SEPARATE SCRIPT from probe.sh. Three things differ for a big
# GUI app, and every one of them produced a wrong conclusion before it was
# handled:
#
#   1. STARTUP IS SLOW. VS Code and Firefox need 40-50 seconds cold in a
#      container. probe.sh waits 7. A short wait looks exactly like an app that
#      ignores XTEST.
#   2. A FIRST-RUN MODAL EATS EVERY KEYSTROKE. VS Code opens on "Sign in to use
#      GitHub Copilot"; the keys go to the dialog and vanish silently. This is
#      what produced the earlier claim that "Electron never receives a
#      keystroke" — it does. `--dismiss` sends Escape twice first.
#   3. THERE IS NO FILE TO READ BACK. These apps hold the text in a widget, so
#      the read-back is ctrl+a ctrl+c and the X clipboard, not a pipe.
#
# The click lands at CLICK_PCT% of the window width so it hits the editing area
# rather than a side panel — VS Code's Chat panel on the right is *also* a text
# target, and typing into it is a pass that proves nothing.
#
# Usage: probe-gui.sh LABEL WAIT_S CLICK_PCT -- command to launch the app
set -u
LABEL="$1"; WAIT="$2"; CLICK_PCT="$3"; shift 3
export DISPLAY=:99 MOZ_DISABLE_CONTENT_SANDBOX=1
pkill -f "Xvfb :99" 2>/dev/null; sleep 1
Xvfb :99 -screen 0 1400x900x24 >/dev/null 2>&1 &
sleep 2
# Mandatory. Without a window manager nothing holds focus and xdotool falls
# back to XSendEvent, which applications ignore for security.
openbox >/dev/null 2>&1 &
sleep 2
# Scratch dir for the app to keep its profile in. Created here rather than left
# to the caller because Firefox does NOT create a missing `--profile` directory:
# it opens a 566x108 error dialog and waits, which from the outside is
# indistinguishable from the browser having failed to start.
PROFILE_DIR="/tmp/probe-$LABEL"
mkdir -p "$PROFILE_DIR"
"$@" >/dev/null 2>&1 &
sleep "$WAIT"

# Pick the newest window that is REAL. `xdotool search` also returns ids that
# have already been destroyed and openbox's own frames; querying one of those
# gives BadWindow, and under `set -u` the empty geometry then kills the script
# with "X: unbound variable" — which looks like a probe bug rather than a bad
# window id. Validate before committing to a candidate.
WIN=""; SAW_SMALL=""
for cand in $(xdotool search --onlyvisible --name . 2>/dev/null | tac); do
    geo=$(xdotool getwindowgeometry --shell "$cand" 2>/dev/null) || continue
    [ -z "$geo" ] && continue
    eval "$geo"
    # Skip 1x1 placeholders and small dialogs. A small window is a *finding*,
    # not an absence — report it separately, because "the app put an error box
    # on screen" and "the app never started" need completely different fixes.
    if [ "${WIDTH:-0}" -gt 200 ] && [ "${HEIGHT:-0}" -gt 200 ]; then WIN="$cand"; break; fi
    SAW_SMALL="${WIDTH:-?}x${HEIGHT:-?}"
done
if [ -z "$WIN" ]; then
    import -window root "/work/${LABEL}.png" 2>/dev/null
    [ -n "$SAW_SMALL" ] \
        && echo "RESULT|$LABEL|DIALOG_ONLY|only a ${SAW_SMALL} window — see ${LABEL}.png" \
        || echo "RESULT|$LABEL|NO_WINDOW|"
    exit 0
fi
xdotool windowactivate --sync "$WIN" 2>/dev/null; sleep 3

# Dismiss whatever first-run dialog is in front. Harmless if there is none.
#
# PROBE_PRE_KEYS is for the ones Escape cannot answer: Zed stacks an
# "Unsupported GPU" notice on top of a "Trust this project?" prompt, and the
# second needs Return, not Escape. Set it to a space-separated xdotool key list.
for k in ${PROBE_PRE_KEYS:-Escape Escape}; do xdotool key "$k"; sleep 1; done

eval "$(xdotool getwindowgeometry --shell "$WIN")"
xdotool mousemove $((X + WIDTH * CLICK_PCT / 100)) $((Y + HEIGHT / 2)) click 1
sleep 2

TEXT='kubectl get pods --namespace prod'
xdotool type --delay 20 "$TEXT"
sleep 3
xdotool key ctrl+a; sleep 1; xdotool key ctrl+c; sleep 2

GOT=$(xclip -o -selection clipboard 2>/dev/null | head -c 200 | tr '\n' ' ')
if [ "$GOT" = "$TEXT" ]; then V=EXACT
elif [ -n "$GOT" ]; then V=PARTIAL; else V=NOTHING; fi
# A screenshot is the fastest way to tell "no keystrokes land" from "a dialog
# is in front of the thing you are typing into". Costs nothing on success.
import -window root "/work/${LABEL}.png" 2>/dev/null
echo "RESULT|$LABEL|$V|$GOT"
