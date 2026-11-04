"""The hands-free controls are the Hands-free page of the settings window, not a window of
their own, so nothing user-visible may send anyone to "Settings -> Hands-free controls"."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STALE = re.compile(r"Settings\s*(?:→|->)\s*Hands-free controls")


def test_no_source_or_doc_names_a_settings_location_that_no_longer_exists():
    hits = []
    for base in ("src", "docs"):
        for path in (ROOT / base).rglob("*"):
            if path.suffix not in {".py", ".md"} or not path.is_file():
                continue
            if STALE.search(path.read_text(encoding="utf-8", errors="replace")):
                hits.append(path.relative_to(ROOT).as_posix())
    assert hits == [], f"say 'Settings -> Hands-free' instead in: {hits}"
