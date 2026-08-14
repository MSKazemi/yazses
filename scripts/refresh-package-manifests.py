#!/usr/bin/env python3
"""Recompute package-manager checksums from the real released assets.

Why this exists
---------------
An audit on 2026-08-11 found that every packaging manifest in this repo was stale,
and two of them pointed at GitHub releases that had **never been published** while
still carrying ``PLACEHOLDER_..._SHA256`` where a checksum belonged. A manifest with a
wrong hash is worse than no manifest: Homebrew and winget both refuse the download, so
the first thing a new user sees is a failure that looks like the project is broken.

Hand-copying a hash after every release is exactly the kind of step that gets skipped.
This script derives them instead, straight from the assets attached to the tag, so the
manifests cannot silently drift from what was actually shipped.

Usage
-----
    python scripts/refresh-package-manifests.py --version 2.17.0 --check
    python scripts/refresh-package-manifests.py --version 2.18.0

``--check`` verifies and writes nothing (exit 1 on any mismatch), which is what CI
should run. Without it, the manifests are rewritten in place.

Deliberately stdlib-only -- no requests, no PyYAML -- so it runs under a bare
``/usr/bin/python3`` in a release job with nothing installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = "MSKazemi/yazses"
ROOT = Path(__file__).resolve().parent.parent
CASK = ROOT / "packaging" / "homebrew" / "yazses.rb"
WINGET_DIR = ROOT / "packaging" / "winget" / "manifests" / "m" / "MSKazemi" / "YazSes"
SCOOP = ROOT / "bucket" / "yazses.json"
# The reviewed copy. `bucket/` is what Scoop actually fetches; this one is what a
# reviewer reads in a diff, and a test asserts they are identical. Refreshing only
# the served copy would turn a release into a red suite — and refreshing only the
# reviewed one would ship a stale bucket, which is the silent failure this script
# exists to prevent.
SCOOP_REVIEWED = ROOT / "packaging" / "scoop" / "yazses.json"
PKGBUILD = ROOT / "packaging" / "arch" / "PKGBUILD"
SRCINFO = ROOT / "packaging" / "arch" / ".SRCINFO"

# Inno Setup registers itself as "<AppId>_is1"; the AppId is fixed in
# packaging/windows/installer.iss and must not change between versions, or winget
# will treat every upgrade as a fresh install.
INNO_PRODUCT_CODE = "{F3E8B8A4-1B6C-4F24-9BE8-9B7E58E9C4A2}_is1"


@dataclass(frozen=True)
class Asset:
    """One released file and the digest computed from its actual bytes."""

    name: str
    url: str
    size: int
    sha256: str


def _run(*args: str) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(args)}\n{proc.stderr.strip()}")
    return proc.stdout


def release_info(version: str) -> tuple[dict[str, tuple[str, int]], str]:
    """Return (asset name -> (URL, size), publish date) for tag v<version>.

    The publish date becomes winget's ``ReleaseDate``; taking it from the release
    rather than "today" keeps a regenerated manifest byte-identical, which is what
    makes ``--check`` usable as a CI gate.
    """
    raw = _run(
        "gh", "release", "view", f"v{version}",
        "--repo", REPO, "--json", "assets,publishedAt",
    )
    data = json.loads(raw)
    assets = data.get("assets", [])
    if not assets:
        raise SystemExit(f"release v{version} has no assets (is the tag published?)")
    published = (data.get("publishedAt") or "")[:10]
    return {a["name"]: (a["url"], a["size"]) for a in assets}, published


def fetch_digest(name: str, url: str, expected_size: int) -> Asset:
    """Stream the asset and hash it without holding ~100 MB in memory.

    The size is checked against the release metadata because a truncated download
    hashes perfectly happily -- it just produces a digest for a file nobody has. That
    is the failure this function exists to make impossible.
    """
    digest = hashlib.sha256()
    read = 0
    req = urllib.request.Request(url, headers={"User-Agent": "yazses-manifest-refresh"})
    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310 - github.com only
        while chunk := resp.read(1 << 20):
            digest.update(chunk)
            read += len(chunk)
    if read != expected_size:
        raise SystemExit(
            f"{name}: downloaded {read} bytes but the release says {expected_size}. "
            "Refusing to write a checksum for a partial file."
        )
    return Asset(name=name, url=url, size=expected_size, sha256=digest.hexdigest())


def render_cask(version: str, dmg: Asset, previous: str) -> str:
    """Update only the version and sha256 lines, preserving everything else."""
    out = re.sub(r'^(\s*version\s+)"[^"]*"', rf'\g<1>"{version}"', previous, count=1, flags=re.M)
    out = re.sub(r'^(\s*sha256\s+)"[^"]*"', rf'\g<1>"{dmg.sha256}"', out, count=1, flags=re.M)
    return out


def render_winget(version: str, exe: Asset, release_date: str) -> dict[str, str]:
    installer = f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.installer.1.6.0.schema.json
PackageIdentifier: MSKazemi.YazSes
PackageVersion: {version}
InstallerType: inno
Scope: user
InstallModes:
  - interactive
  - silent
  - silentWithProgress
UpgradeBehavior: install
ProductCode: '{INNO_PRODUCT_CODE}'
MinimumOSVersion: 10.0.19041.0
ReleaseDate: {release_date}
Installers:
  - Architecture: x64
    InstallerUrl: {exe.url}
    InstallerSha256: {exe.sha256.upper()}
ManifestType: installer
ManifestVersion: 1.6.0
"""
    version_manifest = f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.version.1.6.0.schema.json
PackageIdentifier: MSKazemi.YazSes
PackageVersion: {version}
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.6.0
"""
    return {
        "MSKazemi.YazSes.installer.yaml": installer,
        "MSKazemi.YazSes.yaml": version_manifest,
    }


def pypi_sdist_sha256(version: str) -> str:
    """The Arch package builds from the PyPI sdist, not from a GitHub asset.

    PyPI publishes the digest in its JSON API, so this needs no download -- which
    also means the Arch manifests can be refreshed before the binaries finish
    uploading.
    """
    url = f"https://pypi.org/pypi/yazses/{version}/json"
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - pypi.org only
        data = json.load(resp)
    for f in data.get("urls", []):
        if f.get("packagetype") == "sdist":
            return f["digests"]["sha256"]
    raise SystemExit(f"yazses {version} has no sdist on PyPI -- cannot refresh the AUR package")


def render_scoop(version: str, exe: Asset, previous: str) -> str:
    """Rewrite only version/url/hash; the notes and bin/shortcut wiring are prose."""
    data = json.loads(previous)
    data["version"] = version
    arch = data["architecture"]["64bit"]
    arch["url"] = f"{exe.url}#/setup.exe"
    arch["hash"] = exe.sha256
    return json.dumps(data, indent=4) + "\n"


def render_pkgbuild(version: str, sdist_sha: str, previous: str) -> str:
    out = re.sub(r"^pkgver=.*$", f"pkgver={version}", previous, count=1, flags=re.M)
    out = re.sub(r"^sha256sums=\(.*\)$", f"sha256sums=('{sdist_sha}')", out, count=1, flags=re.M)
    return out


def render_srcinfo(version: str, sdist_sha: str, previous: str) -> str:
    out = re.sub(r"^(\tpkgver = ).*$", rf"\g<1>{version}", previous, count=1, flags=re.M)
    out = re.sub(
        r"^(\tsource = ).*$",
        rf"\g<1>https://files.pythonhosted.org/packages/source/y/yazses/yazses-{version}.tar.gz",
        out, count=1, flags=re.M)
    out = re.sub(r"^(\tsha256sums = ).*$", rf"\g<1>{sdist_sha}", out, count=1, flags=re.M)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--version", required=True, help="release version, e.g. 2.17.0")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed manifests match the released assets; write nothing",
    )
    args = parser.parse_args(argv)
    version = args.version.lstrip("v")

    assets, release_date = release_info(version)
    dmg_name = f"YazSes-{version}.dmg"
    exe_name = f"YazSes-{version}-windows-x64.exe"
    problems: list[str] = []

    for needed in (dmg_name, exe_name):
        if needed not in assets:
            problems.append(f"release v{version} has no asset named {needed}")
    if problems:
        for p in problems:
            print(f"ERROR: {p}", file=sys.stderr)
        return 1

    print(f"Hashing the released assets for v{version} (about 200 MB)…")
    dmg = fetch_digest(dmg_name, *assets[dmg_name])
    exe = fetch_digest(exe_name, *assets[exe_name])
    print(f"  {dmg.name}  {dmg.sha256}")
    print(f"  {exe.name}  {exe.sha256}")

    sdist_sha = pypi_sdist_sha256(version)
    print(f"  PyPI sdist                    {sdist_sha}")

    cask_text = render_cask(version, dmg, CASK.read_text(encoding="utf-8"))
    winget_files = render_winget(version, exe, release_date)
    winget_target = WINGET_DIR / version
    # Scoop and Arch were hand-maintained and therefore drifted: at v2.18.2 both
    # still pointed at an older release. The Scoop bucket is served straight out
    # of this repository, so a stale manifest means `scoop update yazses` keeps
    # installing the previous version indefinitely.
    scoop_text = render_scoop(version, exe, SCOOP.read_text(encoding="utf-8"))
    simple = {
        SCOOP: scoop_text,
        SCOOP_REVIEWED: scoop_text,
        PKGBUILD: render_pkgbuild(version, sdist_sha, PKGBUILD.read_text(encoding="utf-8")),
        SRCINFO: render_srcinfo(version, sdist_sha, SRCINFO.read_text(encoding="utf-8")),
    }

    if args.check:
        if CASK.read_text(encoding="utf-8") != cask_text:
            problems.append(f"{CASK.relative_to(ROOT)} is out of date")
        for path, body in simple.items():
            if path.read_text(encoding="utf-8") != body:
                problems.append(f"{path.relative_to(ROOT)} is out of date")
        for filename, body in winget_files.items():
            path = winget_target / filename
            if not path.exists():
                problems.append(f"{path.relative_to(ROOT)} is missing")
            elif path.read_text(encoding="utf-8") != body:
                problems.append(f"{path.relative_to(ROOT)} does not match the released asset")
        if problems:
            for p in problems:
                print(f"ERROR: {p}", file=sys.stderr)
            print("\nRe-run without --check to regenerate.", file=sys.stderr)
            return 1
        print(f"\nOK — every manifest matches the assets released as v{version}.")
        return 0

    CASK.write_text(cask_text, encoding="utf-8")
    winget_target.mkdir(parents=True, exist_ok=True)
    for filename, body in winget_files.items():
        (winget_target / filename).write_text(body, encoding="utf-8")
    for path, body in simple.items():
        path.write_text(body, encoding="utf-8")
    written = ", ".join(str(p.relative_to(ROOT)) for p in simple)
    print(f"\nWrote {CASK.relative_to(ROOT)}, {winget_target.relative_to(ROOT)}/, {written}")
    print(
        "The locale manifest carries prose, not checksums, so it is left alone —\n"
        "copy it from the previous version and edit the description if it changed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
