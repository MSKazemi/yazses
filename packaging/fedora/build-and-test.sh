#!/usr/bin/env bash
# Build the RPM from the spec and prove the result actually works (#77).
#
# This is the acceptance criterion from the issue, run rather than asserted:
# build on a clean Fedora, install the RPM, run `yazses doctor`. It is meant to
# be executed INSIDE a Fedora container so nothing touches the host:
#
#   podman run --rm -v "$PWD:/src:z" fedora:41 /src/packaging/fedora/build-and-test.sh
#   docker run --rm -v "$PWD:/src"    fedora:41 /src/packaging/fedora/build-and-test.sh
#
# `yazses doctor` exits non-zero on a container (no audio device, no session), and
# that is the correct answer there — what is being verified is that the package
# installs, the entry points resolve, and the diagnostics run and report honestly.
set -euo pipefail

SRC=${SRC:-/src}
SPEC="$SRC/packaging/fedora/yazses.spec"

echo "==> installing build tooling"
dnf -y install rpm-build rpmdevtools python3-devel python3-pip gcc kernel-headers \
    portaudio findutils >/dev/null

echo "==> preparing the rpm tree"
rpmdev-setuptree
VERSION=$(awk '/^Version:/ {print $2}' "$SPEC")

# Build from the working tree rather than the PyPI sdist, so the spec is tested
# against the code in this checkout. COPR uses the Source0 URL instead; the
# %prep/%install steps are identical either way.
echo "==> staging yazses-$VERSION.tar.gz from the working tree"
STAGE=$(mktemp -d)
mkdir -p "$STAGE/yazses-$VERSION"
tar -C "$SRC" \
    --exclude=.git --exclude=.venv --exclude='*.pyc' --exclude=__pycache__ \
    -cf - . | tar -C "$STAGE/yazses-$VERSION" -xf -
tar -C "$STAGE" -czf ~/rpmbuild/SOURCES/"yazses-$VERSION.tar.gz" "yazses-$VERSION"

echo "==> rpmbuild"
rpmbuild -bb "$SPEC" --define "_sourcedir $HOME/rpmbuild/SOURCES"

RPM=$(find ~/rpmbuild/RPMS -name 'yazses-*.rpm' | head -1)
echo "==> built: $RPM"
rpm -qip "$RPM" | sed -n '1,12p'

echo "==> installing it"
dnf -y install "$RPM" >/dev/null

echo "==> the acceptance criterion"
command -v yazses
yazses --version
# Diagnostics must RUN and report; a container legitimately fails several checks.
yazses doctor || echo "(doctor exited non-zero — expected in a container with no audio device or session)"
echo "==> OK"
