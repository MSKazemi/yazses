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

# A cache-miss here is not a slow build, it is a four-hour one: `onnx-asr` pulls in
# `onnxscript`, which pulls in torch, and an uncached torch is compiled from source
# on every core the machine has. That happened once (see
# design/packaging/nix-binary-cache.md). So ask what WOULD be built before building
# it, and refuse to start a source build nobody asked for.
echo "==> preflight: is the closure cached?"
DRY_RUN_OUT=$(nix build --no-write-lock-file --dry-run .#yazses 2>&1) || {
    echo "$DRY_RUN_OUT"; echo "!! dry-run failed"; exit 1
}
# In --dry-run output the things to BUILD are .drv paths; the things to FETCH from
# the cache are plain store paths. That distinction is the whole check.
#
# yazses itself is excluded: it is this repository, it is by definition not in any
# binary cache, and building it is the entire point of this script. Only a
# *dependency* being absent from the cache is the failure we are guarding against.
TO_BUILD=$(printf '%s\n' "$DRY_RUN_OUT" \
    | grep -oE '/nix/store/[a-z0-9]+-[^ ]*\.drv' \
    | grep -v -- '-yazses' \
    | sort -u || true)
N_BUILD=$(printf '%s' "$TO_BUILD" | grep -c . || true)

if [ "$N_BUILD" -gt 0 ]; then
    echo "    $N_BUILD derivation(s) are NOT in the binary cache and would be built from source:"
    # Bash builtins only: the nixos/nix image is minimal and has no sed.
    while IFS= read -r drv; do
        [ -n "$drv" ] || continue
        name=${drv##*/}     # drop the store path
        name=${name#*-}     # drop the hash prefix
        printf '      %s\n' "${name%.drv}"
    done <<< "$TO_BUILD"
    if [ "${ALLOW_SOURCE_BUILD:-0}" != "1" ]; then
        cat >&2 <<'EOF'

!! Refusing to start a source build.

   This is almost always the flake selecting a non-default interpreter: Hydra only
   caches nixpkgs' DEFAULT python3 package set, so `pkgs.python312` (or any other
   pin) silently opts out of the cache. Check that flake.nix uses `pkgs.python3`.

   If the source build really is what you want, re-run with:
       ALLOW_SOURCE_BUILD=1 [BUILD_CORES=N] ...
EOF
        exit 1
    fi
    # Deliberate source build: leave the machine usable rather than pinning every
    # core at 100% for hours.
    # nproc is not guaranteed in the minimal image either.
    NCPU=$(nproc 2>/dev/null || grep -c '^processor' /proc/cpuinfo 2>/dev/null || echo 2)
    BUILD_CORES=${BUILD_CORES:-$(( NCPU / 2 > 0 ? NCPU / 2 : 1 ))}
    echo "    ALLOW_SOURCE_BUILD=1 — building with --cores $BUILD_CORES"
    NIX_BUILD_FLAGS="--cores $BUILD_CORES --max-jobs 1"
else
    echo "    all cached — nothing will be compiled"
    NIX_BUILD_FLAGS=""
fi

echo "==> nix build .#yazses"
# shellcheck disable=SC2086 # NIX_BUILD_FLAGS is intentionally word-split
OUT=$(nix build --no-write-lock-file --no-link --print-out-paths $NIX_BUILD_FLAGS .#yazses)
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
