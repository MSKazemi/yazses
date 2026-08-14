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

#: How a translation cites the authoritative English text. Absolute, because the
#: translations moved to `docs/<locale>/index.md` and render on two surfaces —
#: only GitHub can reach a repo-root file from there by a relative path.
ENGLISH_README = "https://github.com/MSKazemi/yazses#readme"
REPO_BLOB = "https://github.com/MSKazemi/yazses/blob/main"

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
        """Repo-relative path — `docs/de/index.md`, not a bare `index.md`.

        Every translation is now called `index.md`, so the bare filename names 28
        different files and a problem report would not say which one.
        """
        try:
            return self.path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
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


#: How the switcher line opens, in every locale. It is deliberately English: the
#: line is navigation between languages, so it has to be legible to a reader who
#: cannot yet read the page they are on.
SWITCHER_PREFIX = "**Read this in other languages:**"


def switcher_targets(text: str) -> list[str]:
    """Local markdown link targets on the language-switcher line.

    Found by its opening rather than by line number: a translation now carries
    docs-site front matter, so the switcher is no longer the first line of the
    file — and a line-1 assumption would silently return no targets at all,
    turning every switcher check into a vacuous pass.
    """
    line = next(
        (ln for ln in text.splitlines() if ln.startswith(SWITCHER_PREFIX)), ""
    )
    return [
        t for t in _LINK_RE.findall(line)
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


def absolute_equivalents(source_text: str) -> set[str]:
    """Absolute URLs that mean the same repo file as a relative link in the source.

    The English README sits at the repo root and links to its neighbours by name —
    `](LICENSE)`, `](CITATION.cff)`. A translation two directories down cannot, so
    it names the same file by URL. Those are the *same resource*, and without this
    every translation would raise a note for each one: ~84 lines of noise through
    the channel that is supposed to surface the one genuinely stale path.
    """
    out = {ENGLISH_README}
    for target in _LINK_RE.findall(source_text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        out.add(f"{REPO_BLOB}/{target.lstrip('./')}")
    return out


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
    known_locales: set[Path],
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
    if ENGLISH_README not in text:
        report.problems.append(f"{where}: has no link back to the English {SOURCE}")
    for target in switcher_targets(text):
        # Resolved against the file's own directory, which is the only reading
        # that is true on both surfaces this page renders on.
        resolved = (locale.path.parent / target.split("#", 1)[0]).resolve()
        if not resolved.exists():
            report.problems.append(f"{where}: language-switcher link {target!r} does not exist")

    # Every locale must be reachable from every other. Only "the links that ARE
    # here resolve" was checked, so adding a language and regenerating the
    # switchers silently dropped three existing translations from every README —
    # each file was individually valid and the set was broken.
    listed = {
        (locale.path.parent / t.split("#", 1)[0]).resolve()
        for t in switcher_targets(text)
    }
    for other in sorted(known_locales):
        if other.resolve() in (locale.path.resolve(), *listed):
            continue
        report.problems.append(
            f"{where}: language switcher does not list {other.parent.name} — a reader "
            "of this locale cannot reach it"
        )

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
    source_urls = project_urls(source_text, host_hints=host_hints) | absolute_equivalents(
        source_text
    )
    for url in sorted(project_urls(text, host_hints=host_hints) - source_urls):
        report.notes.append(f"{where}: project URL {url} does not appear in {SOURCE}")

    return report


def load_locales(root: Path) -> list[Locale]:
    """Discover the translations, which live at `docs/<locale>/index.md`.

    Identified by the `yazses-l10n` metadata block rather than by directory name.
    `docs/` is full of other `index.md` files — `use-cases/`, `mobile/`, `how-to/`
    — and a name-based rule would either sweep those in or need a hand-maintained
    list of language codes that goes stale the first time one is added.
    """
    out: list[Locale] = []
    for path in sorted(root.glob("docs/*/index.md")):
        text = path.read_text(encoding="utf-8")
        meta = parse_metadata(text)
        # Either mark makes it a translation. Requiring the metadata block would
        # let a file that *lost* its block drop out of the check set entirely —
        # the missing-metadata problem would delete its own detector.
        if not meta and SWITCHER_PREFIX not in text:
            continue
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
    known = {loc.path for loc in locales}

    if args.list:
        print(f"{'file':<24} {'locale':<8} {'status':<8} {'scope':<10} source_sha")
        for loc in locales:
            print(f"{loc.name:<24} {loc.locale:<8} {loc.status:<8} "
                  f"{loc.scope:<10} {loc.source_sha}")
        return 0

    if not locales:
        print("No docs/<locale>/index.md translations found.")
        return 0

    problems: list[str] = []
    notes: list[str] = []
    for loc in locales:
        report = check_locale(
            loc, loc.path.read_text(encoding="utf-8"), source_text, known_locales=known
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
