#!/usr/bin/env bash
# Adds one or more .deb files to the gh-pages apt repository and rebuilds indexes.
# Usage: bash scripts/update-apt-repo.sh <path-to.deb> [<path-to.deb>...] <gpg-key-id>
# Env: GITHUB_TOKEN, GITHUB_REPOSITORY
#
# Every architecture in one call, deliberately. The repo advertises
# `Architectures "amd64 arm64 all"`, and apt clients on an advertised arch that
# has no package see a repository with nothing in it for them. Taking a single
# .deb made that the default outcome: at v2.21.0 the release built amd64 and
# arm64, this script accepted one, and the job died with "Expected 1 .deb, got 2"
# — so *neither* arch was published.
set -euo pipefail

(( $# >= 2 )) || { echo "usage: $0 <path-to.deb> [<path-to.deb>...] <gpg-key-id>" >&2; exit 2; }

# The key id is always last; everything before it is a .deb.
KEY_ID="${*: -1}"
DEB_FILES=()
for arg in "${@:1:$#-1}"; do
  [[ "$arg" == *.deb ]] || { echo "ERROR: not a .deb: $arg" >&2; exit 1; }
  DEB_FILES+=("$(realpath "$arg")")
done

git config user.email "actions@github.com"
git config user.name "GitHub Actions"
git remote set-url origin \
  "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}"

# Stash the .deb outside the working tree
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
cp "${DEB_FILES[@]}" "$TMPDIR/"

# Checkout gh-pages, creating it as an orphan if it doesn't exist yet
git fetch origin
if git ls-remote --exit-code --heads origin gh-pages >/dev/null 2>&1; then
  git checkout gh-pages
else
  git checkout --orphan gh-pages
  git rm -rf . 2>/dev/null || true
fi

mkdir -p apt

# Copy the new .debs into apt/ (remove old versions first, so the pool holds
# exactly one version across every architecture rather than accumulating).
mapfile -t debs < <(ls "$TMPDIR"/*.deb 2>/dev/null)
(( ${#debs[@]} >= 1 )) || { echo "ERROR: no .deb in $TMPDIR"; exit 1; }

# One architecture must never be published twice in a run: two files for the same
# arch means the caller merged artifacts wrongly, and the pool would end up with
# whichever `cp` ran last, silently.
declare -A seen_arch=()
for deb in "${debs[@]}"; do
  arch="$(dpkg-deb --field "$deb" Architecture 2>/dev/null || echo "")"
  [[ -n "$arch" ]] || { echo "ERROR: cannot read Architecture from $deb"; exit 1; }
  [[ -z "${seen_arch[$arch]:-}" ]] || { echo "ERROR: two .debs for $arch"; exit 1; }
  seen_arch[$arch]=1
done
echo "Publishing ${#debs[@]} .deb(s): ${!seen_arch[*]}"

rm -f apt/yazses_*.deb
cp "${debs[@]}" apt/

# Install tools (idempotent on Ubuntu runners)
sudo apt-get install -y -q dpkg-dev apt-utils 2>/dev/null

cd apt

# Build package indexes
dpkg-scanpackages --multiversion . > Packages
gzip -9c Packages > Packages.gz

# Export public key for users to download
gpg --armor --export "$KEY_ID" > KEY.gpg

# Generate Release file (apt-ftparchive adds correct checksums)
cat > apt-ftparchive.conf <<'EOF'
APT::FTPArchive::Release::Origin "YazSes";
APT::FTPArchive::Release::Label "YazSes";
APT::FTPArchive::Release::Suite "stable";
APT::FTPArchive::Release::Codename "stable";
APT::FTPArchive::Release::Architectures "amd64 arm64 all";
APT::FTPArchive::Release::Components "main";
APT::FTPArchive::Release::Description "YazSes APT Repository";
EOF
apt-ftparchive -c apt-ftparchive.conf release . > Release
rm apt-ftparchive.conf

# Sign — loopback mode avoids any TTY/pinentry requirement in CI
gpg --batch --yes --pinentry-mode loopback --passphrase-file /tmp/gpg-passphrase \
  --default-key "$KEY_ID" --clearsign -o InRelease Release
gpg --batch --yes --pinentry-mode loopback --passphrase-file /tmp/gpg-passphrase \
  --default-key "$KEY_ID" --armor --detach-sign -o Release.gpg Release

cd ..

# Create landing page if it doesn't exist yet
if [ ! -f index.html ]; then
  cat > index.html <<'HTML'
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>YazSes APT Repository</title></head>
<body>
<h1>YazSes APT Repository</h1>
<pre>
curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/gh-pages/apt/KEY.gpg \
  | sudo gpg --dearmor --yes -o /usr/share/keyrings/yazses.gpg
echo "deb [signed-by=/usr/share/keyrings/yazses.gpg] https://raw.githubusercontent.com/MSKazemi/yazses/gh-pages/apt ./" \
  | sudo tee /etc/apt/sources.list.d/yazses.list
sudo apt update
sudo apt install yazses
</pre>
</body>
</html>
HTML
fi

git add -A
git commit -m "apt: publish yazses $(basename "$DEB_FILE")"
git push origin gh-pages
