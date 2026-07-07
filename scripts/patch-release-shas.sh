#!/usr/bin/env bash
# Patch SHA256 placeholders in Homebrew formula and winget manifests after CI build.
# Usage: bash scripts/patch-release-shas.sh <version>
# Example: bash scripts/patch-release-shas.sh 1.0.0
#
# Requires: curl, sha256sum (Linux) or shasum (macOS), gh (GitHub CLI, for auth)
# The script downloads release assets from GitHub, computes SHA256s, and patches:
#   packaging/homebrew/yazses-v1.rb
#   packaging/winget/manifests/m/MSKazemi/YazSes/<version>/MSKazemi.YazSes.installer.yaml
set -euo pipefail

VERSION="${1:-}"
[[ -n "$VERSION" ]] || { echo "Usage: $0 <version>  (e.g. 1.0.0)"; exit 1; }

TAG="v${VERSION}"
BASE_URL="https://github.com/MSKazemi/yazses/releases/download/${TAG}"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

sha256_of() {
  local file="$1"
  if command -v sha256sum &>/dev/null; then
    sha256sum "$file" | awk '{print $1}'
  else
    shasum -a 256 "$file" | awk '{print $1}'
  fi
}

download() {
  local name="$1"
  local url="${BASE_URL}/${name}"
  echo "  Downloading ${name}..."
  curl -fsSL --retry 3 -o "${TMPDIR}/${name}" "$url"
  sha256_of "${TMPDIR}/${name}"
}

echo "==> Fetching release assets for ${TAG}"

MACOS_ARM64="yazses-${TAG}-aarch64-apple-darwin.tar.gz"
MACOS_X86="yazses-${TAG}-x86_64-apple-darwin.tar.gz"
WIN_X64="yazses-${TAG}-x86_64-pc-windows-msvc.zip"
WIN_ARM64="yazses-${TAG}-aarch64-pc-windows-msvc.zip"

SHA_MACOS_ARM64=$(download "$MACOS_ARM64")
SHA_MACOS_X86=$(download "$MACOS_X86")
SHA_WIN_X64=$(download "$WIN_X64")
# arm64 Windows zip is optional — skip gracefully if not yet in release
if curl -fsSL --head "${BASE_URL}/${WIN_ARM64}" &>/dev/null; then
  SHA_WIN_ARM64=$(download "$WIN_ARM64")
else
  echo "  Warning: ${WIN_ARM64} not found in release — skipping arm64 winget entry"
  SHA_WIN_ARM64="NOT_RELEASED"
fi

echo ""
echo "==> SHA256 values:"
echo "  macOS arm64  : $SHA_MACOS_ARM64"
echo "  macOS x86_64 : $SHA_MACOS_X86"
echo "  Windows x64  : $SHA_WIN_X64"
echo "  Windows arm64: $SHA_WIN_ARM64"

FORMULA="packaging/homebrew/yazses-v1.rb"
echo ""
echo "==> Patching ${FORMULA}"
sed -i.bak \
  -e "s/PLACEHOLDER_MACOS_ARM64_SHA256/${SHA_MACOS_ARM64}/" \
  -e "s/PLACEHOLDER_MACOS_X86_64_SHA256/${SHA_MACOS_X86}/" \
  "$FORMULA"
rm -f "${FORMULA}.bak"
echo "    Done."

WINGET_INSTALLER="packaging/winget/manifests/m/MSKazemi/YazSes/${VERSION}/MSKazemi.YazSes.installer.yaml"
echo "==> Patching ${WINGET_INSTALLER}"
sed -i.bak \
  -e "s/PLACEHOLDER_WIN64_V100_SHA256/${SHA_WIN_X64}/" \
  -e "s/PLACEHOLDER_WINARM64_V100_SHA256/${SHA_WIN_ARM64}/" \
  "$WINGET_INSTALLER"
rm -f "${WINGET_INSTALLER}.bak"
echo "    Done."

echo ""
echo "==> Verification — grep for remaining placeholders:"
grep -r "PLACEHOLDER" packaging/homebrew/yazses-v1.rb packaging/winget/manifests/m/MSKazemi/YazSes/"${VERSION}"/ \
  && { echo "ERROR: placeholders remain — check the output above"; exit 1; } \
  || echo "    None found. All SHAs patched."

echo ""
echo "==> Next steps:"
echo "    git add packaging/homebrew/yazses-v1.rb '${WINGET_INSTALLER}'"
echo "    git commit -m 'chore(release): patch SHA256s for ${TAG}'"
echo "    # For Homebrew tap: copy yazses-v1.rb → MSKazemi/homebrew-yazses repo and open PR"
echo "    # For winget: open PR to microsoft/winget-pkgs with the updated manifests"
