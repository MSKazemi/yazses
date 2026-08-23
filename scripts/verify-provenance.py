#!/usr/bin/env python3
"""Check that every artifact a release *claims* provenance for actually has one.

Why this exists
---------------
Four workflows call ``actions/attest-build-provenance``, and
``tests/test_release_provenance_assets.py`` proves the *workflow* attaches a bundle.
Nothing proved that a published artifact ends up with an attestation GitHub will
serve. The audit on 2026-08-24 found ``gh attestation verify`` mentioned exactly once
in this repository -- inside a comment.

That gap matters because the failure is silent in the direction that hurts. An
attestation step that silently produces nothing leaves a release that looks signed,
scores well, and cannot be verified by anyone who tries. v2.19.0 already shipped a
near-miss of this shape: the ``.dmg`` attest step globbed the wrong directory, failed,
and skipped the upload -- caught only because the asset went missing too.

How it checks
-------------
By **digest**, never by downloading. ``SHA256SUMS.txt`` is published with every
release, and GitHub serves attestations at
``/repos/{owner}/{repo}/attestations/sha256:{digest}``. So a full check costs a few
API calls rather than 370 MB of installers -- which is what makes it cheap enough to
run on every release rather than once.

Which assets need one is **derived from the workflows** that do the attesting, not
listed here. A hand-written list is the defect it would be guarding against: add a
channel, forget the list, and the check reports success over an artifact nobody
attested.

Deliberately stdlib-only, like ``refresh-package-manifests.py`` -- it has to run under
a bare ``/usr/bin/python3`` in a release job with nothing installed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
REPO = os.environ.get("GH_REPO", "MSKazemi/yazses")

#: `subject-path:` of an `actions/attest-build-provenance` step.
_SUBJECT = re.compile(r"^\s*subject-path:\s*(.+?)\s*$", re.M)
_SUMS_LINE = re.compile(r"^([0-9a-f]{64})\s+\*?(.+)$")


def attested_suffixes(workflow_dir: Path = WORKFLOWS) -> set[str]:
    """Every file extension some workflow attests, read out of the workflows.

    Derived rather than declared: a new packaging channel that attests a `.pkg`
    is covered the day it is added, and a channel that stops attesting stops
    being required to.
    """
    found: set[str] = set()
    for path in sorted(workflow_dir.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if "attest-build-provenance" not in text:
            continue
        for raw in _SUBJECT.findall(text):
            value = raw.strip().strip("\"'")
            suffix = Path(value).suffix
            # `${{ matrix.arch }}.exe` still ends in a real suffix; an image
            # attestation (subject-name/digest, no path) contributes nothing.
            if suffix and suffix.isascii() and re.fullmatch(r"\.[a-z0-9]+", suffix):
                found.add(suffix)
    return found


def parse_sums(text: str) -> dict[str, str]:
    """`SHA256SUMS.txt` -> {filename: digest}."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _SUMS_LINE.match(line.strip())
        if m:
            out[m.group(2).strip()] = m.group(1)
    return out


def needing_attestation(sums: dict[str, str], suffixes: set[str]) -> dict[str, str]:
    """The subset of a release's assets that some workflow claims to attest."""
    return {n: d for n, d in sums.items() if Path(n).suffix in suffixes}


def _fetch(url: str, token: str | None) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def attestation_count(digest: str, token: str | None) -> int:
    """How many attestations GitHub serves for this digest. 0 means unverifiable."""
    url = f"https://api.github.com/repos/{REPO}/attestations/sha256:{digest}"
    try:
        return len(_fetch(url, token).get("attestations") or [])
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 0
        raise


def release_sums(tag: str, token: str | None) -> str:
    url = f"https://github.com/{REPO}/releases/download/{tag}/SHA256SUMS.txt"
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def _token() -> str | None:
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    try:
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", help="release tag, e.g. v2.30.0")
    ap.add_argument("--sums", type=Path, help="a local SHA256SUMS.txt instead of the release")
    args = ap.parse_args(argv)
    if not args.tag and not args.sums:
        print("ERROR: pass --tag or --sums", file=sys.stderr)
        return 2

    # Read the module global at call time, not the default bound at definition
    # time -- otherwise this can never be pointed at another tree, and the
    # empty-derivation guard below is untestable and therefore unproven.
    suffixes = attested_suffixes(WORKFLOWS)
    if not suffixes:
        print(
            "ERROR: no workflow appears to attest anything. Either the attestation "
            "steps were removed, or this script can no longer read them -- and a "
            "check that finds nothing to do reports success.",
            file=sys.stderr,
        )
        return 1
    print(f"attested suffixes (derived from .github/workflows): {sorted(suffixes)}")

    # The token is resolved only where a request is actually made: `--sums` with no
    # attestable asset must not shell out to `gh` at all, so the offline paths stay
    # offline and testable on a host with no gh and no network.
    text = (
        args.sums.read_text(encoding="utf-8") if args.sums else release_sums(args.tag, _token())
    )
    sums = parse_sums(text)
    if not sums:
        print("ERROR: SHA256SUMS.txt parsed to nothing", file=sys.stderr)
        return 1

    wanted = needing_attestation(sums, suffixes)
    if not wanted:
        print(f"no attestable artifact among {len(sums)} assets — nothing to verify")
        return 0

    token = _token()
    missing = []
    for name, digest in sorted(wanted.items()):
        count = attestation_count(digest, token)
        print(f"  {'OK ' if count else 'MISSING'}  {name}  {count} attestation(s)")
        if not count:
            missing.append(name)

    if missing:
        print(
            "\nERROR: these artifacts are published without a verifiable attestation:\n"
            + "\n".join(f"  {n}" for n in missing),
            file=sys.stderr,
        )
        return 1
    print(f"\nall {len(wanted)} attestable artifact(s) verified by digest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
