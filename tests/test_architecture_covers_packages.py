"""design/architecture.md must name every package under ``src/yazses/``.

The architecture reference had drifted: a shipped headline package (``meeting/``) had no
section at all, and nothing noticed because no test compared the document to the tree.
This pure test closes that gap with a ratchet:

* every package directory is named as ``<pkg>/`` somewhere in ``design/architecture.md``, or
* it is in :data:`UNDOCUMENTED`, an explicit allowlist with a reason on each line.

The allowlist can only shrink. An entry whose package is now documented, or whose package no
longer exists, fails the test, so documenting a package (or deleting one) forces the line out.
Adding a *new* package to the allowlist is a visible, reviewable act, not a silent default.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "yazses"
ARCH = ROOT / "design" / "architecture.md"

_TODO = (
    "TODO: no per-package section yet; described only in its module docstring and the "
    "generated docs/features.md"
)

#: package -> why it has no mention in design/architecture.md yet. Shrink, never grow.
UNDOCUMENTED: dict[str, str] = {
    "acoustic": _TODO,
    "acronyms": _TODO,
    "affect": _TODO,
    "audioguard": _TODO,
    "autopair": _TODO,
    "biasing": _TODO,
    "bookmarks": _TODO,
    "brailleout": _TODO,
    "breath": _TODO,
    "casetransform": _TODO,
    "chords": _TODO,
    "cite": _TODO,
    "cliphistory": _TODO,
    "cmdspotter": _TODO,
    "coach": _TODO,
    "code": _TODO,
    "codec": _TODO,
    "compose": _TODO,
    "compute": _TODO,
    "condense": _TODO,
    "contour": _TODO,
    "convert": _TODO,
    "corrdict": _TODO,
    "crowdproof": _TODO,
    "diacritize": _TODO,
    "diagramvox": _TODO,
    "echo": _TODO,
    "fieldaware": _TODO,
    "fileopen": _TODO,
    "findreplace": _TODO,
    "focusprofile": _TODO,
    "gec": _TODO,
    "gitvoice": _TODO,
    "hatselect": _TODO,
    "hesitation": _TODO,
    "interpret": _TODO,
    "involuntary": _TODO,
    "itn": _TODO,
    "jump": _TODO,
    "langroute": _TODO,
    "lipread": _TODO,
    "loadguard": _TODO,
    "markup": _TODO,
    "math": _TODO,
    "mood": _TODO,
    "mousegrid": _TODO,
    "outline": _TODO,
    "pronunciation": _TODO,
    "prosodypunct": _TODO,
    "rag": _TODO,
    "readback": _TODO,
    "reask": _TODO,
    "redaction": _TODO,
    "reflow": _TODO,
    "rewrite": _TODO,
    "safeglyph": _TODO,
    "screenplay": _TODO,
    "scribe": _TODO,
    "scrub": _TODO,
    "selfrepair": _TODO,
    "sembr": _TODO,
    "shellpipe": _TODO,
    "sign": _TODO,
    "slotfill": _TODO,
    "smartpaste": _TODO,
    "snippets": _TODO,
    "spatialvad": _TODO,
    "spelling": _TODO,
    "spokenregex": _TODO,
    "spreadsheet": _TODO,
    "srpace": _TODO,
    "srscap": _TODO,
    "styleguard": _TODO,
    "suggestmode": _TODO,
    "symbols": _TODO,
    "tablecsv": _TODO,
    "temporal": _TODO,
    "timeline": _TODO,
    "translate": _TODO,
    "translit": _TODO,
    "verbatim": _TODO,
    "vocaljoystick": _TODO,
    "voiceguard": _TODO,
    "voicehealth": _TODO,
    "voiceprivacy": _TODO,
    "voicetimer": _TODO,
    "wakeword": _TODO,
    "whispermode": _TODO,
    "windowctl": _TODO,
    "wordfind": _TODO,
    "wordgoal": _TODO,
}


def _packages() -> set[str]:
    return {
        p.name for p in SRC.iterdir()
        if p.is_dir() and (p / "__init__.py").exists()
    }


def _mentioned(pkg: str, text: str) -> bool:
    return re.search(r"(?<![\w])" + re.escape(pkg) + r"/", text) is not None


def _uncovered(packages: set[str], text: str) -> set[str]:
    return {p for p in packages if not _mentioned(p, text)}


def test_every_package_is_in_the_architecture_doc_or_allowlisted():
    text = ARCH.read_text(encoding="utf-8")
    missing = sorted(_uncovered(_packages(), text) - set(UNDOCUMENTED))
    assert not missing, (
        "These src/yazses packages are not named as '<pkg>/' in design/architecture.md. "
        "Document them there (preferred) or, with a reason, add them to UNDOCUMENTED: "
        f"{missing}"
    )


def test_allowlist_only_shrinks():
    text = ARCH.read_text(encoding="utf-8")
    packages = _packages()
    gone = sorted(set(UNDOCUMENTED) - packages)
    assert not gone, f"UNDOCUMENTED names packages that no longer exist: {gone}"
    now_documented = sorted(set(UNDOCUMENTED) - _uncovered(packages, text))
    assert not now_documented, (
        f"These are now documented in design/architecture.md; remove them from "
        f"UNDOCUMENTED: {now_documented}"
    )


def test_every_allowlist_entry_has_a_reason():
    blank = sorted(k for k, v in UNDOCUMENTED.items() if not v.strip())
    assert not blank, f"UNDOCUMENTED entries without a reason: {blank}"


def test_meeting_mode_is_documented():
    # The package that prompted this test; it must not slip back onto the allowlist.
    assert "meeting" not in UNDOCUMENTED
    assert _mentioned("meeting", ARCH.read_text(encoding="utf-8"))


def test_checker_notices_an_unlisted_package():
    # Mutation check kept as a permanent test: a package the doc does not name is reported.
    text = ARCH.read_text(encoding="utf-8")
    assert "zz_not_a_package" in _uncovered({"zz_not_a_package", "meeting"}, text)
    assert "meeting" not in _uncovered({"meeting"}, text)
