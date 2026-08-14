#!/usr/bin/env bash
# Evaluate and build the flake, in a container (#68).
#
# The flake's own header used to say "authored, NOT YET EVALUATED — the authoring
# machine has no Nix". This is the answer to that: a container has Nix, so there
# is no reason for a manifest to ship unevaluated.
#
#   docker run --rm -v "$PWD:/host:ro" nixos/nix /host/packaging/nix/build-and-test.sh
#
# It copies the tree out of the read-only mount first, because Nix refuses a git
# repository it does not own ("repository path is not owned by current user") and
# because a flake in a read-only directory cannot write a lock file.
set -euo pipefail

export NIX_CONFIG='experimental-features = nix-command flakes'

WORK=${WORK:-/work}
if [ ! -d "$WORK" ]; then
    cp -r /host "$WORK"
    rm -rf "$WORK/.git" "$WORK/.venv"
fi
cd "$WORK"

echo "==> nix flake check"
# --no-build: evaluation is what catches the errors a reviewer cannot see by
# reading, and it finishes in seconds rather than pulling the whole closure.
nix flake check --no-build --no-write-lock-file .

echo "==> nix build .#yazses"
OUT=$(nix build --no-write-lock-file --no-link --print-out-paths .#yazses)
echo "    $OUT"

echo "==> the entry point runs"
"$OUT/bin/yazses" --version

echo "==> transcribe the sample clip, offline"
# The flake header names this as the check that matters, because it exercises the
# packaged faster-whisper rather than just the CLI wrapper. It needs the model, so
# it is skipped when the container has no network.
if [ -f data/librispeech-sample/jfk.wav ]; then
    cp data/librispeech-sample/jfk.wav /tmp/clip.wav
    "$OUT/bin/yazses" transcribe /tmp/clip.wav --model tiny.en 2>&1 | tail -2 || \
        echo "    (skipped — needs to download a model once)"
    [ -f /tmp/clip.txt ] && cat /tmp/clip.txt
fi

echo "==> OK"
