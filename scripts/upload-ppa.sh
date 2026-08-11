#!/usr/bin/env bash
# Builds and uploads a Debian source package to Launchpad PPA.
# Usage: bash scripts/upload-ppa.sh <version> <key-id> <ppa-address>
# Example: bash scripts/upload-ppa.sh 0.1.3 ABCDEF1234567890 ppa:mskazemi/yazses
# Env: DEBEMAIL, DEBFULLNAME
set -euo pipefail

VERSION="$1"
KEY_ID="$2"
PPA="$3"

export DEBEMAIL="${DEBEMAIL:-mohsen.seyedkazemi@gmail.com}"
export DEBFULLNAME="${DEBFULLNAME:-Mohsen Seyedkazemi Ardebili}"

# Upload for each Ubuntu LTS series
for SERIES in jammy noble; do
  echo "=== Building for $SERIES ==="

  # Write changelog for this version + series
  cat > debian/changelog <<EOF
yazses ($VERSION) $SERIES; urgency=medium

  * Release $VERSION.

 -- $DEBFULLNAME <$DEBEMAIL>  $(date -Ru)
EOF

  # Build signed source package
  debuild -S -sa -k"$KEY_ID" --no-lintian 2>&1

  # Upload to Launchpad
  dput "$PPA" "../yazses_${VERSION}_source.changes"

  echo "Uploaded yazses $VERSION for $SERIES"

  # Clean up build artifacts before next iteration
  rm -f "../yazses_${VERSION}"*
done
