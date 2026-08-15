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

# De-duplicate by what apt actually keys on: Package + Version + Architecture.
#
# `build-deb.sh` declares `Architecture: all` (YazSes is pure Python) and uses
# `dpkg --print-architecture` only to name the file. So the amd64 and arm64 matrix
# jobs produce two files that are the *same package* to apt, differing in filename
# alone. Copying both puts two entries with one Package/Version into the index.
# Identical triples are therefore interchangeable: keep one, say so. A genuine
# disagreement -- two files claiming one architecture with different versions -- is
# still an error, because then the pool's contents would depend on `cp` ordering.
declare -A chosen=()
for deb in "${debs[@]}"; do
  # The trailing newline is load-bearing: without it `read` hits EOF, returns
  # non-zero, and `set -e` kills the run with no message at all.
  read -r pkg ver arch < <(dpkg-deb --show --showformat='${Package} ${Version} ${Architecture}\n' "$deb")
  [[ -n "$arch" ]] || { echo "ERROR: cannot read control fields from $deb"; exit 1; }
  key="${pkg}_${ver}_${arch}"
  if [[ -n "${chosen[$key]:-}" ]]; then
    echo "  skipping $(basename "$deb") — same $key as $(basename "${chosen[$key]}")"
    continue
  fi
  # Same arch, different package or version: ambiguous, and silently resolvable
  # only by file order. Refuse.
  for seen_key in "${!chosen[@]}"; do
    [[ "${seen_key##*_}" == "$arch" ]] || continue
    echo "ERROR: two different packages claim Architecture $arch: $seen_key and $key"
    exit 1
  done
  chosen[$key]="$deb"
done

echo "Publishing ${#chosen[@]} .deb(s) from ${#debs[@]} file(s): ${!chosen[*]}"
rm -f apt/yazses_*.deb
cp "${chosen[@]}" apt/

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
