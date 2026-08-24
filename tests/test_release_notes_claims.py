"""The release-notes body in `release.yml` is written once and published at every tag.

Every sentence in it is therefore a standing claim about a version nobody has cut yet.
Two shapes go stale silently and neither shows up in a build:

* **A version series.** "the v0 build is unsigned" was still being published on the
  v2.30.0 release page, three majors after it stopped being true as written.
* **A promise about the future.** "signing is coming" costs nothing to keep, but it is
  the sentence a reader checks the release page for, so it must not name a version.

The body cannot be checked for truth by a test, so what is checked is that it never
*pins itself to a version at all* — a claim with no version in it cannot go stale.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / ".github" / "workflows" / "release.yml"

# "the v0 build", "in v1 builds", "since v2 releases" — a product-series claim.
SERIES_CLAIM = re.compile(r"\bv\d+\s+(?:build|release|version)s?\b", re.I)


def _release_bodies() -> dict[str, str]:
    """Every `body:` block handed to a release-creating step, keyed by step name.

    Derived from the workflow rather than named here, so a second release step is covered
    the day it is added instead of the day someone remembers this file exists.
    """
    doc = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
    bodies: dict[str, str] = {}
    for job in doc["jobs"].values():
        for step in job.get("steps") or []:
            body = (step.get("with") or {}).get("body")
            if isinstance(body, str):
                bodies[step.get("name", step.get("uses", "?"))] = body
    return bodies


def test_a_release_body_is_found_at_all() -> None:
    """Without this, every assertion below passes on an empty dict."""
    bodies = _release_bodies()
    assert bodies, "no release step with a `body:` — the guard below is checking nothing"
    assert any(len(b) > 500 for b in bodies.values()), (
        "every body found is tiny; the install instructions moved somewhere unguarded"
    )


def test_no_release_body_pins_itself_to_a_version_series() -> None:
    stale = {
        name: SERIES_CLAIM.findall(body)
        for name, body in _release_bodies().items()
        if SERIES_CLAIM.search(body)
    }
    assert not stale, (
        f"release notes make a version-series claim that every later tag republishes: {stale}"
    )
