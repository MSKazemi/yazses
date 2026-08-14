#!/usr/bin/env bash
# Build the AUR package and prove the result works (#67).
#
# The issue's acceptance criterion, run rather than asserted: `makepkg -si` on a
# clean Arch container, then `yazses doctor`. Meant to run INSIDE a container so
# nothing touches the host:
#
#   podman run --rm -v "$PWD:/src:z" archlinux:base-devel /src/packaging/arch/build-and-test.sh
#   docker run --rm -v "$PWD:/src"    archlinux:base-devel /src/packaging/arch/build-and-test.sh
#
# `yazses doctor` exits non-zero in a container (no session, no audio device, no
# `input` group) and that is the correct answer there. What is verified is that
# the PKGBUILD parses, .SRCINFO matches it, the package builds and installs, and
# the entry points resolve.
set -euo pipefail

SRC=${SRC:-/src}
PKGDIR=$SRC/packaging/arch

echo "==> base tooling"
pacman -Sy --noconfirm --needed base-devel git pyalpm >/dev/null 2>&1 || \
    pacman -Sy --noconfirm --needed base-devel git >/dev/null

# makepkg refuses to run as root, by design.
id -u builder >/dev/null 2>&1 || useradd -m builder
echo "builder ALL=(ALL) NOPASSWD: ALL" >/etc/sudoers.d/builder

WORK=/home/builder/build
rm -rf "$WORK"; mkdir -p "$WORK"
cp "$PKGDIR/PKGBUILD" "$WORK/"
cp "$PKGDIR"/*.install "$WORK/" 2>/dev/null || :
chown -R builder:builder "$WORK"

echo "==> PKGBUILD parses, and .SRCINFO matches it"
sudo -u builder bash -c "cd $WORK && makepkg --printsrcinfo > .SRCINFO.generated"
if ! diff -u "$PKGDIR/.SRCINFO" "$WORK/.SRCINFO.generated"; then
    echo "::error:: .SRCINFO is out of date — regenerate with 'makepkg --printsrcinfo > .SRCINFO'"
    exit 1
fi
echo "    .SRCINFO matches"

echo "==> classifying dependencies"
# Two runtime deps live in the AUR (python-faster-whisper, python-sounddevice),
# and faster-whisper pulls a further AUR chain of its own — ctranslate2,
# tokenizers, onnxruntime, av. **`makepkg` never fetches AUR dependencies**; only
# an AUR helper (yay, paru) resolves them recursively. That is normal for Arch and
# is how a user actually installs this, but it means a plain `makepkg -si` in a
# bare container cannot complete, and saying so is more useful than a generic
# "target not found".
aur_deps=()
while read -r dep; do
    name=${dep%%[<>=]*}
    [ -n "$name" ] || continue
    pacman -Si "$name" >/dev/null 2>&1 || aur_deps+=("$name")
done < <(sudo -u builder bash -c "cd $WORK && source PKGBUILD && printf '%s\n' \"\${depends[@]}\"")
echo "    from the AUR: ${aur_deps[*]:-none}"

echo "==> namcap (packaging lint)"
pacman -S --noconfirm --needed namcap >/dev/null 2>&1 && \
    sudo -u builder bash -c "cd $WORK && namcap PKGBUILD" || \
    echo "    (namcap unavailable — skipped)"

echo "==> installing makedepends"
# --nodeps below skips makedepends as well as runtime deps, so they go in by hand
# first. (Without this, build() dies with "No module named build" — which looks
# like a PKGBUILD bug and is not one.)
mapfile -t makedeps < <(sudo -u builder bash -c "cd $WORK && source PKGBUILD && printf '%s\n' \"\${makedepends[@]}\"")
if ((${#makedeps[@]})); then
    echo "    ${makedeps[*]}"
    pacman -S --noconfirm --needed "${makedeps[@]}" >/dev/null
fi

echo "==> makepkg --nodeps: does the package itself build and install?"
# --nodeps deliberately: the AUR chain above is the helper's job, and what is
# being tested here is THIS PKGBUILD — that it fetches, verifies, builds and
# packages, and that the entry points land where the docs say.
sudo -u builder bash -c "cd $WORK && makepkg --nodeps --noconfirm"
PKG=$(ls "$WORK"/*.pkg.tar.* | head -1)
echo "    built: $(basename "$PKG")"
pacman -U --noconfirm --nodeps --nodeps "$PKG" >/dev/null

echo "==> installing the runtime deps that ARE in the official repos"
# Everything except the AUR chain, so the CLI can actually start. What remains
# missing is exactly the set an AUR helper would have fetched.
repo_deps=()
while read -r dep; do
    name=${dep%%[<>=]*}
    [ -n "$name" ] || continue
    pacman -Si "$name" >/dev/null 2>&1 && repo_deps+=("$name")
done < <(sudo -u builder bash -c "cd $WORK && source PKGBUILD && printf '%s\n' \"\${depends[@]}\"")
((${#repo_deps[@]})) && pacman -S --noconfirm --needed "${repo_deps[@]}" >/dev/null

echo "==> the entry point resolves"
command -v yazses
# --version only touches typer, so it works before the heavy AUR deps are
# present; anything that loads a model would not, and should not be claimed here.
yazses --version

cat <<'NOTE'

==> RESULT
    PKGBUILD parses, .SRCINFO matches, the package builds and installs, and
    `yazses --version` runs. (On Arch the binary resolves via /usr/sbin, which is
    a symlink to /usr/bin — that is the distribution's layout, not the package's.)

    NOT verified here: `yazses doctor` end to end, because the AUR dependency
    chain (faster-whisper -> ctranslate2, tokenizers, onnxruntime, av) is
    resolved by an AUR helper, not by makepkg. On a real Arch machine:

        yay -S yazses     # or: paru -S yazses

NOTE
