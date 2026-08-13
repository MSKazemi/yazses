#!/usr/bin/env python3
"""Check README translations for drift, without rewriting a word of them (#166).

English is the source of truth; the translations are native human work. Those two
facts together rule out the obvious tool — anything that regenerates or "fixes" a
translation would overwrite a contributor's writing with machine output, and the
contributor would rightly stop contributing.

So this checker is **read-only and non-destructive**. It never edits a
translation; it reports what has drifted and leaves the fix to a human who reads
the language. What it can check without understanding prose:

* **Every language-switcher link resolves.** A dead switcher link is the most
  common breakage and the easiest to miss, because the file it points at is
  usually one someone renamed.
* **Every locale links back to the English README** and carries a sync-metadata
  block, so "which English commit was this translated from?" has an answer.
* **Commands and project URLs are preserved verbatim.** Translating prose is the
  point; translating `yazses features enable tray` is a bug that hands a reader a
  command that does not exist. This is the check that catches real damage.
* **A locale marked `draft` shows a review banner**, so a reader knows the text
  has not been reviewed by a native speaker yet.

The metadata block is an HTML comment, which renders as nothing on GitHub:

    <!-- yazses-l10n: locale=hi; source_sha=96711bc; scope=full; status=active -->

Usage:
    uv run python scripts/check-translations.py           # report drift
    uv run python scripts/check-translations.py --list    # print the parsed matrix
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "README.md"

# `<!-- yazses-l10n: key=value; key=value -->`, anywhere in the first lines.
_META_RE = re.compile(r"<!--\s*yazses-l10n:\s*(?P<body>[^>]*?)\s*-->", re.I)
_LINK_RE = re.compile(r"\[[^\]]*\]\((?P<target>[^)\s]+)\)")
_FENCE_RE = re.compile(r"```[^\n]*\n(?P<body>.*?)```", re.S)
# A yazses invocation inside a fenced block, normalised to a single space.
_COMMAND_RE = re.compile(r"^\s*(?:\$\s*)?(?P<cmd>(?:uv run )?yazses[a-z-]*\s[^\n#]*)", re.M)
_URL_RE = re.compile(r"https?://[^\s)\]<>\"']+")

VALID_STATUS = ("active", "draft", "stale")


@dataclass
class Locale:
    """One translated README and the metadata it declares."""

    path: Path
    locale: str = ""
    source_sha: str = ""
    scope: str = ""
    status: str = ""
    reviewer: str = ""

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class Report:
    """Findings. `problems` fail the run; `notes` are informational."""

    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


# ── pure parsing ─────────────────────────────────────────────────────────────


def parse_metadata(text: str) -> dict[str, str]:
    """Extract the `yazses-l10n` comment into a dict. Missing block → empty."""
    match = _META_RE.search(text)
    if not match:
        return {}
    out: dict[str, str] = {}
    for part in match.group("body").split(";"):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        out[key.strip().lower()] = value.strip()
    return out


def switcher_targets(text: str) -> list[str]:
    """Local markdown link targets on the language-switcher line (line 1)."""
    first = text.lstrip().splitlines()[0] if text.strip() else ""
    return [
        t for t in _LINK_RE.findall(first)
        if not t.startswith(("http://", "https://", "#"))
    ]


def commands_in(text: str) -> set[str]:
    """Every `yazses …` invocation inside fenced blocks, whitespace-normalised.

    Scoped to fenced blocks deliberately: a command named in prose is often
    inflected by the surrounding sentence, and flagging that would produce noise
    a translator cannot act on.
    """
    found: set[str] = set()
    for fence in _FENCE_RE.finditer(text):
        for m in _COMMAND_RE.finditer(fence.group("body")):
            found.add(" ".join(m.group("cmd").split()))
    return found


def project_urls(text: str, *, host_hints: tuple[str, ...]) -> set[str]:
    """Project-owned URLs, ignoring third-party links a translator may add."""
    return {
        u.rstrip(".,;:")
        for u in _URL_RE.findall(text)
        if any(h in u for h in host_hints)
    }


def check_locale(
    locale: Locale,
    text: str,
    source_text: str,
    *,
    existing_files: set[str],
    host_hints: tuple[str, ...] = ("github.com/MSKazemi", "mskazemi.com"),
) -> Report:
    """Validate one translation against the English source. Pure."""
    report = Report()
    where = locale.name

    if not locale.locale:
        report.problems.append(
            f"{where}: no `yazses-l10n` metadata block — add "
            "`<!-- yazses-l10n: locale=xx; source_sha=…; scope=…; status=… -->` "
            "(see docs/localization/STATUS.md)"
        )
    if locale.status and locale.status not in VALID_STATUS:
        report.problems.append(
            f"{where}: status={locale.status!r} is not one of {list(VALID_STATUS)}"
        )
    if not locale.source_sha:
        report.problems.append(f"{where}: metadata has no source_sha")

    # Links back to English, and every switcher target exists. A bare mention of
    # the filename is not a link — the reader needs somewhere to click.
    if f"]({SOURCE})" not in text:
        report.problems.append(f"{where}: has no markdown link back to {SOURCE}")
    for target in switcher_targets(text):
        if target.split("#", 1)[0] not in existing_files:
            report.problems.append(f"{where}: language-switcher link {target!r} does not exist")

    # A draft must say so where a reader will see it, not only in metadata.
    if locale.status == "draft" and "draft" not in text.lower()[:2000]:
        report.problems.append(
            f"{where}: status=draft but no visible review banner near the top"
        )

    # The damaging drift: a command that was translated, or invented.
    source_commands = commands_in(source_text)
    for command in sorted(commands_in(text) - source_commands):
        report.problems.append(
            f"{where}: command {command!r} is not in {SOURCE} — commands must be "
            "copied verbatim, never translated"
        )

    # A project URL that exists only in the translation is usually a stale path.
    source_urls = project_urls(source_text, host_hints=host_hints)
    for url in sorted(project_urls(text, host_hints=host_hints) - source_urls):
        report.notes.append(f"{where}: project URL {url} does not appear in {SOURCE}")

    return report


def load_locales(root: Path) -> list[Locale]:
    """Discover `README.<locale>.md` beside the English source."""
    out: list[Locale] = []
    for path in sorted(root.glob("README.*.md")):
        meta = parse_metadata(path.read_text(encoding="utf-8"))
        out.append(Locale(
            path=path,
            locale=meta.get("locale", ""),
            source_sha=meta.get("source_sha", ""),
            scope=meta.get("scope", ""),
            status=meta.get("status", ""),
            reviewer=meta.get("reviewer", ""),
        ))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="print the parsed matrix and exit")
    args = ap.parse_args()

    source_path = ROOT / SOURCE
    source_text = source_path.read_text(encoding="utf-8")
    locales = load_locales(ROOT)
    existing = {p.name for p in ROOT.glob("*.md")}

    if args.list:
        print(f"{'file':<20} {'locale':<8} {'status':<8} {'scope':<10} source_sha")
        for loc in locales:
            print(f"{loc.name:<20} {loc.locale:<8} {loc.status:<8} "
                  f"{loc.scope:<10} {loc.source_sha}")
        return 0

    if not locales:
        print("No README.<locale>.md files found.")
        return 0

    problems: list[str] = []
    notes: list[str] = []
    for loc in locales:
        report = check_locale(
            loc, loc.path.read_text(encoding="utf-8"), source_text, existing_files=existing
        )
        problems += report.problems
        notes += report.notes

    for note in notes:
        print(f"note: {note}")
    if problems:
        print("\nTranslation drift:")
        for p in problems:
            print(f"  - {p}")
        print(f"\n{len(problems)} problem(s). Nothing was modified — these are for a "
              "human who reads the language.")
        return 1

    print(f"{len(locales)} translation(s) checked, no drift.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
