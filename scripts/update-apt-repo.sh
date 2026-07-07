#!/usr/bin/env bash
# Adds a .deb to the gh-pages apt repository and rebuilds indexes.
# Usage: bash scripts/update-apt-repo.sh <path-to.deb> <gpg-key-id>
# Env: GITHUB_TOKEN, GITHUB_REPOSITORY
set -euo pipefail

DEB_FILE="$(realpath "$1")"
KEY_ID="$2"

git config user.email "actions@github.com"
git config user.name "GitHub Actions"
git remote set-url origin \
  "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}"

# Stash the .deb outside the working tree
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
cp "$DEB_FILE" "$TMPDIR/"

# Checkout gh-pages, creating it as an orphan if it doesn't exist yet
git fetch origin
if git ls-remote --exit-code --heads origin gh-pages >/dev/null 2>&1; then
  git checkout gh-pages
else
  git checkout --orphan gh-pages
  git rm -rf . 2>/dev/null || true
fi

mkdir -p apt

# Copy new .deb into apt/ (remove old versions first)
# Guard: ensure exactly one .deb
mapfile -t debs < <(ls "$TMPDIR"/*.deb 2>/dev/null)
[[ ${#debs[@]} -eq 1 ]] || { echo "ERROR: expected 1 .deb in $TMPDIR, got ${#debs[@]}"; exit 1; }
rm -f apt/yazses_*.deb
cp "${debs[0]}" apt/

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
curl -fsSL https://mskazemi.github.io/yazses/apt/KEY.gpg \
  | sudo gpg --dearmor --yes -o /usr/share/keyrings/yazses.gpg
echo "deb [signed-by=/usr/share/keyrings/yazses.gpg] https://mskazemi.github.io/yazses/apt ./" \
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
