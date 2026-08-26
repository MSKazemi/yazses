#!/usr/bin/env python3
"""Check that a release's SHA256SUMS.txt actually describes the assets it ships.

v2.32.0 published a checksum that matched **neither** Windows installer. The release had
been run twice for the same tag; on the second run every asset already existed from the
first, so `checksums.yml`'s "wait for assets to appear" loop -- which counts *names* --
was satisfied immediately, hashed the previous run's binaries, and the still-running
Windows build overwrote them two to three minutes later. The .deb and .dmg matched only
because their builds happened to finish ten seconds before the hashing step.

Windows builds are unsigned, so SHA256SUMS.txt is the only integrity signal a Windows user
has, and `docs/code-signing.md` tells them to check it. A wrong hash there reads as
"your download was corrupted or tampered with".

Two checks, cheapest first:

* **--quick** (default) compares each asset's `updatedAt` against SHA256SUMS.txt's. Any
  asset written *after* the checksum file cannot be described by it. One API call, no
  downloads. Validated against five releases: it predicted the two v2.32.0 mismatches and
  v2.31.0's match, and hashing confirmed all three.
* **--deep** downloads every asset and hashes it. Slow and bandwidth-heavy, but it is the
  only check that cannot be fooled -- verify the *artifact*, never the file the same
  machinery generated alongside it.

Maintainer tooling, deliberately not in `src/yazses/`: ADR-019's egress inventory fails the
build on a new outbound call inside the package.

    scripts/verify-release-assets.py v2.32.0
    scripts/verify-release-assets.py v2.32.0 --deep
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SUMS = "SHA256SUMS.txt"
ARTIFACT_SUFFIXES = (".exe", ".dmg", ".deb")


def _gh(*args: str) -> str:
    out = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise SystemExit(f"gh failed: {' '.join(args)}\n{out.stderr.strip()}")
    return out.stdout


def assets(tag: str) -> list[dict]:
    return json.loads(_gh("release", "view", tag, "--json", "assets"))["assets"]


def quick(tag: str) -> list[str]:
    """Assets written after SHA256SUMS.txt -- it cannot possibly describe them."""
    rows = assets(tag)
    sums = next((a for a in rows if a["name"] == SUMS), None)
    if sums is None:
        raise SystemExit(f"{tag}: no {SUMS} asset -- nothing to verify against")
    return sorted(a["name"] for a in rows
                  if a["name"].endswith(ARTIFACT_SUFFIXES) and a["updatedAt"] > sums["updatedAt"])


def deep(tag: str) -> tuple[list[str], list[str]]:
    """Download every artifact and hash it. Returns (matched, mismatched)."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        _gh("release", "download", tag, "-p", SUMS, "-O", str(d / SUMS), "--clobber")
        published = {}
        for line in (d / SUMS).read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2:
                published[parts[1]] = parts[0].lower()

        ok, bad = [], []
        for name, want in sorted(published.items()):
            if not name.endswith(ARTIFACT_SUFFIXES):
                continue
            target = d / "asset.bin"
            _gh("release", "download", tag, "-p", name, "-O", str(target), "--clobber")
            h = hashlib.sha256()
            with target.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            (ok if h.hexdigest() == want else bad).append(name)
            target.unlink(missing_ok=True)
        return ok, bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--deep", action="store_true", help="download and hash every artifact")
    a = ap.parse_args()

    stale = quick(a.tag)
    if stale:
        print(f"FAIL {a.tag}: written AFTER {SUMS}, so it cannot describe them:")
        for n in stale:
            print(f"       {n}")
    else:
        print(f"ok   {a.tag}: no artifact is newer than {SUMS}")

    if not a.deep:
        return 1 if stale else 0

    ok, bad = deep(a.tag)
    for n in ok:
        print(f"  MATCH    {n}")
    for n in bad:
        print(f"  MISMATCH {n}")
    if bad:
        print(f"\nFAIL {a.tag}: {len(bad)} artifact(s) do not match {SUMS}")
    return 1 if (bad or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
