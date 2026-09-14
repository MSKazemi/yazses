#!/usr/bin/env python3
"""Compare the live Snap Store listing against snap/snapcraft.yaml.

The listing drifted for a month across three releases and nothing could see it.
On 2026-09-13 the published page still told every visitor to run `yazses setup`
as one of "all four commands are required" -- a command strict confinement
forbids, corrected in the repository on 2026-08-26 -- and still made the
unqualified claim "nothing leaves your machine", corrected on 2026-08-14,
four paragraphs above its own sentence about downloading a model.

Nothing in the repository pushes store metadata: there is no
`snapcraft upload-metadata` in any workflow, script or Makefile target. The
store's own "Update metadata on release" evidently did not carry these fields
either. So the manifest and the page people actually read are two independent
documents that no one was diffing.

This diffs them. It is **maintainer tooling and deliberately not in `src/`** --
ADR-019's egress guard fails the build on a new outbound call inside the
package, and the same reasoning that keeps `scripts/research-watch.py` out
applies here. The endpoint is the public, unauthenticated store API, so it
needs no credentials.

    make store-check          # or: python scripts/check-store-listing.py

Exit 0 when the page matches, 1 when it has drifted, 2 when it could not be
checked -- an unreachable store must not read as "in sync".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "snap/snapcraft.yaml"
API = "https://api.snapcraft.io/v2/snaps/info/{name}?fields=summary,description,title,website,contact"

# Constructions that must never appear on the published page, each with the
# reason. Regexes rather than substrings, and that distinction is load-bearing:
# a bare "yazses setup" search also matches our own corrective sentence, "`yazses
# setup` is not an installation step for the snap". A detector that fires on the
# fix as well as the bug gets ignored, which is how the drift survived in the
# first place. Match the harmful framing instead.
FORBIDDEN: tuple[tuple[str, str], ...] = (
    (
        r"all four commands|yazses setup\s*[-\u2013\u2014]\s*provisions",
        "the page presents `yazses setup` as a required install step. Strict "
        "confinement forbids it: it cannot install host packages, change group "
        "membership or configure a host service, so every user following the "
        "instructions is sent down a path that cannot work (fixed in the "
        "repository by 3807a72, 2026-08-26).",
    ),
    (
        r"nothing leaves your machine",
        "unqualified, and the same description says first run downloads the "
        "speech model. The claim must carry 'by default' (fixed by d7e6096, "
        "2026-08-14).",
    ),
    (
        r"stable is amd64 today",
        "stable publishes amd64 and arm64; the sentence sends arm64 users to "
        "--edge for no reason.",
    ),
)


def manifest_fields() -> dict[str, str]:
    """Read summary/description out of the manifest without a YAML dependency."""
    text = MANIFEST.read_text(encoding="utf-8")
    summary = re.search(r"^summary:\s*(.+?)\s*$", text, re.M)
    body = re.search(r"^description: \|\n(.*?)(?=^\S)", text, re.M | re.S)
    if not summary or not body:
        raise SystemExit("could not parse summary/description from snapcraft.yaml")
    description = "\n".join(line[2:] if line.startswith("  ") else line
                            for line in body.group(1).splitlines())
    return {"summary": summary.group(1), "description": description.strip()}


def store_fields(name: str, timeout: float) -> dict[str, str]:
    req = urllib.request.Request(
        API.format(name=name), headers={"Snap-Device-Series": "16"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return json.load(fh)["snap"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", default="yazses")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()

    local = manifest_fields()
    try:
        remote = store_fields(args.name, args.timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Exit 2, never 0: "could not check" is not "in sync". A watcher that
        # reports success when it could not reach its target is the failure it
        # was built to prevent.
        print(f"COULD NOT CHECK the store listing: {exc}", file=sys.stderr)
        return 2

    problems: list[str] = []

    for field in ("summary", "description"):
        if _norm(local[field]) != _norm(remote.get(field, "")):
            problems.append(
                f"{field} DIFFERS between snapcraft.yaml and the published page"
            )

    published = _norm(remote.get("description", "") + " " + remote.get("summary", ""))
    for pattern, why in FORBIDDEN:
        if re.search(pattern, published):
            problems.append(f"published page: {why}")

    if not problems:
        print(f"Snap Store listing for {args.name!r} matches snapcraft.yaml.")
        return 0

    print(f"Snap Store listing for {args.name!r} has DRIFTED:\n", file=sys.stderr)
    for p in problems:
        print(f"  - {p}\n", file=sys.stderr)
    print(
        "Nothing in this repository pushes store metadata. Fix it by editing the\n"
        "Listing page at https://snapcraft.io/yazses/listing, or by running\n"
        "`snapcraft upload-metadata <built.snap>` — note that overwrites\n"
        "store-side edits, so check the banner and screenshots afterwards.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
