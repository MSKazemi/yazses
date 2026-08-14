#!/usr/bin/env python3
"""Emit a README translation skeleton filled from a per-locale string table.

**This does not translate anything.** The prose lives in `translations.py` beside
it and is written by a person (or reviewed by one); this script only assembles the
parts that must be identical in every locale and are easy to get wrong by hand:

* the language-switcher line, which must list every locale that exists and link to
  files that actually exist — the check that fails most often;
* the `yazses-l10n` metadata block, including `source_sha`, so "which English
  commit was this translated from?" always has an answer;
* the draft banner, which `scripts/check-translations.py` requires whenever
  `status=draft` and which must be visible near the top rather than only in
  metadata;
* the commands, copied **verbatim** from the English README. Translating
  `yazses quickstart` hands a reader a command that does not exist, and it is the
  single most damaging thing a translation can do.

Regenerating a locale rewrites only the generated scaffolding; the prose comes
from the table, so editing the table is how a reviewer improves the text.

    uv run python scripts/gen-readme-translation.py --all
    uv run python scripts/gen-readme-translation.py --locale fa
    uv run python scripts/check-translations.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from translations import HUMAN_LOCALES, LOCALES  # noqa: E402

# Commands are copied from the English README verbatim. Keep this list a SUBSET of
# what `check-translations.py` finds there, or the check fails by design.
QUICKSTART = "yazses quickstart\nyazses start"

INSTALL_LINUX = (
    "bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)"
)
INSTALL_APT = (
    "bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)"
)


def _english() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def badge_block() -> str:
    """The contiguous badge block, copied verbatim from the English README.

    Copied rather than restated: `tests/test_contributors_wall.py` requires every
    translation to show the same all-contributors count, and
    `tests/test_citation_metadata.py` requires the same DOI. Both are numbers that
    change, and a hand-maintained copy in 25 files is 25 chances to be wrong.
    """
    lines = _english().splitlines()
    block = [ln for ln in lines if ln.startswith("[![")]
    return "\n".join(block)


def contributors_block() -> str:
    """The all-contributors wall, verbatim, markers included."""
    text = _english()
    start = text.index("<!-- ALL-CONTRIBUTORS-LIST:START")
    end = text.index("<!-- ALL-CONTRIBUTORS-LIST:END") + len("<!-- ALL-CONTRIBUTORS-LIST:END -->")
    return text[start:end]


def source_sha() -> str:
    """The English README's current commit, for the metadata block."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%h", "--", "README.md"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def switcher(current: str) -> str:
    """The line-1 language switcher, with *current* as plain text."""
    entries = []
    english = "English" if current != "en" else "**English**"
    entries.append(english if current == "en" else "[English](README.md)")
    # Generated drafts and human translations together — leaving the human ones out
    # silently dropped Hindi, Russian and Chinese from every switcher the first time
    # this ran.
    everything = {code: spec["name"] for code, spec in LOCALES.items()}
    everything.update(HUMAN_LOCALES)
    for code, label in sorted(everything.items(), key=lambda kv: kv[1]):
        entries.append(label if code == current else f"[{label}](README.{code}.md)")
    return "**Read this in other languages:** " + " · ".join(entries)


def render(code: str, spec: dict, sha: str) -> str:
    t = spec["strings"]
    rtl = spec.get("rtl", False)
    badges = badge_block()
    wall = contributors_block()
    body = f"""{switcher(code)}
<!-- yazses-l10n: locale={code}; source=README.md; source_sha={sha}; scope=partial; status=draft -->

> ⚠️ **{t['draft_title']}** — {t['draft_body']}
>
> *This is a machine-assisted **draft** translation, not yet reviewed by a native
> speaker. English is authoritative: [README.md](README.md). Improving it is a
> welcome first contribution — see [issue #{spec['issue']}](https://github.com/MSKazemi/yazses/issues/{spec['issue']}).*

# YazSes

{badges}

{t['pitch']}

## {t['install_heading']}

| {t['platform']} | {t['command']} |
|---|---|
| **Linux** | `{INSTALL_LINUX}` |
| **Linux** (Debian/Ubuntu, APT) | `{INSTALL_APT}` |
| **{t['any_os']}** (Python ≥ 3.11) | `pipx install yazses` |

```bash
{QUICKSTART}
```

{t['first_run']}

## {t['does_heading']}

- **{t['does_1_title']}** — {t['does_1']}
- **{t['does_2_title']}** — {t['does_2']}
- **{t['does_3_title']}** — {t['does_3']}

## {t['privacy_heading']}

{t['privacy']}

## {t['more_heading']}

{t['more']}

- [{t['link_docs']}](https://mskazemi.com/yazses/)
- [{t['link_readme']}](README.md)
- [{t['link_issues']}](https://github.com/MSKazemi/yazses/issues)

---

## Contributors

{wall}
"""
    if rtl:
        # The switcher must stay on line 1 for the checker, so it goes ABOVE the
        # wrapper rather than inside it — wrapping the whole file would push it to
        # line 2 and the check would fail. Everything after it is right-to-left.
        first, rest = body.split("\n", 1)
        body = f'{first}\n\n<div dir="rtl">\n\n{rest}\n</div>\n'
    return body


def _update_status_page(sha: str) -> None:
    """Keep docs/localization/STATUS.md listing every shipped translation.

    A test enforces this. It exists because the status page is the one surface a
    would-be translator reads before starting, and a language missing from it looks
    like a language nobody has claimed.
    """
    path = ROOT / "docs" / "localization" / "STATUS.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    marker = "<!-- generated-drafts:start -->"
    end_marker = "<!-- generated-drafts:end -->"
    rows = [
        f"| {spec['name']} (`{code}`) | "
        f"[README.{code}.md](https://github.com/MSKazemi/yazses/blob/main/README.{code}.md) | "
        f"partial | *needed* | `{sha}` | draft | "
        f"needs a native reviewer — [#{spec['issue']}]"
        f"(https://github.com/MSKazemi/yazses/issues/{spec['issue']}) |"
        for code, spec in sorted(LOCALES.items(), key=lambda kv: kv[1]["name"])
    ]
    block = marker + "\n" + "\n".join(rows) + "\n" + end_marker
    if marker in text and end_marker in text:
        head = text[: text.index(marker)]
        tail = text[text.index(end_marker) + len(end_marker) :]
        text = head + block + tail
    else:
        anchor = "**Scope** is what the translation claims to cover"
        insert = (
            "\n" + block + "\n\nThe rows above are **machine-assisted drafts**, "
            "generated by `scripts/gen-readme-translation.py` from the string table in "
            "`scripts/translations.py`. Each one says so in the reader's own language at "
            "the top of the file. **Reviewing one is a much smaller job than translating "
            "a README from scratch**, and it is the single most useful thing a native "
            "speaker can do here — correct the prose in the string table and regenerate.\n\n"
        )
        text = text.replace(anchor, insert + anchor, 1)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--locale", help="only this locale")
    ap.add_argument("--all", action="store_true", help="every locale in the table")
    ap.add_argument("--check", action="store_true", help="fail if a file is out of date")
    args = ap.parse_args()

    if not args.all and not args.locale:
        ap.error("pass --all or --locale XX")

    sha = source_sha()
    codes = [args.locale] if args.locale else sorted(LOCALES)
    problems = []
    for code in codes:
        if code not in LOCALES:
            ap.error(f"unknown locale {code!r}; known: {', '.join(sorted(LOCALES))}")
        text = render(code, LOCALES[code], sha)
        path = ROOT / f"README.{code}.md"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                problems.append(path.name)
            continue
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.name}")

    # Every existing README's switcher must list the new locales too, or their
    # links go stale the moment a language is added.
    if not args.check:
        for existing, current in (("README.md", "en"), ("README.hi.md", "hi"),
                                  ("README.ru.md", "ru"), ("README.zh-CN.md", "zh-CN")):
            path = ROOT / existing
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            if lines and lines[0].startswith("**Read this in other languages:**") or \
               (lines and "](README.md)" in lines[0]):
                lines[0] = switcher(current) + "\n"
                path.write_text("".join(lines), encoding="utf-8")
                print(f"updated switcher in {existing}")

    if not args.check:
        _update_status_page(sha)

    if problems:
        print("out of date: " + ", ".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
