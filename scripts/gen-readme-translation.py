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

#: Where a translation cites the authoritative English text. Absolute on purpose:
#: the translations render on two surfaces now (GitHub and the docs site) and only
#: one of them can reach a repo-root file by a relative path.
ENGLISH_README = "https://github.com/MSKazemi/yazses#readme"
REPO_BLOB = "https://github.com/MSKazemi/yazses/blob/main"

#: Every translation lives at `docs/<lang>/index.md` so the docs site can give it a
#: language-rooted URL, an `hreflang` set and a `canonical` — none of which a
#: `blob/main/README.xx.md` page can carry.
def translation_path(code: str) -> Path:
    return ROOT / "docs" / code / "index.md"


def _english() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def badge_block() -> str:
    """The contiguous badge block from the English README. **Not used any more.**

    Kept because it documents why the badges are absent from the translations, which
    is otherwise the kind of omission someone restores in good faith.

    The badges are repo furniture — CI status, PyPI version, licence, Zenodo DOI.
    They earn their place above a README that a developer is reading in a code host.
    A translation is now `docs/<lang>/index.md`, a landing page whose job is to be
    found and read, and `docs/index.md` — the English page it declares itself an
    alternate of — carries no badges either.

    There is also a hard reason. `material/privacy` downloads every external asset at
    build time so no viewer's IP reaches a third party, and **zenodo.org answers that
    downloader with 403** while serving the same badge to a browser. One DOI badge on
    one translated page therefore fails the entire docs build, every time.
    """
    lines = _english().splitlines()
    block = [ln for ln in lines if ln.startswith("[![")]
    return "\n".join(block).replace("](LICENSE)", f"]({REPO_BLOB}/LICENSE)")


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
    """The line-1 language switcher, with *current* as plain text.

    Paths depend on where the file being written lives. The English README stays at
    the repo root; every translation is `docs/<lang>/index.md`, so that it is a real
    page on the docs site — the only surface that can carry the `hreflang` and
    `canonical` tags a GitHub blob page has no `<head>` to hold.

    The relative forms below resolve identically on GitHub and in mkdocs, which is
    what lets one file serve both. From `docs/de/index.md`, `../fr/index.md` is
    `docs/fr/index.md` either way, and `../index.md` is the English front page
    either way — the docs home on the site, its source on GitHub.
    """
    def link(code: str) -> str:
        if current == "en":  # written at the repo root
            return f"docs/{code}/index.md"
        return f"../{code}/index.md"  # written at docs/<current>/index.md

    entries = []
    english = "English" if current != "en" else "**English**"
    entries.append(english if current == "en" else "[English](../index.md)")
    # Generated drafts and human translations together — leaving the human ones out
    # silently dropped Hindi, Russian and Chinese from every switcher the first time
    # this ran.
    everything = {code: spec["name"] for code, spec in LOCALES.items()}
    everything.update(HUMAN_LOCALES)
    for code, label in sorted(everything.items(), key=lambda kv: kv[1]):
        entries.append(label if code == current else f"[{label}]({link(code)})")
    return "**Read this in other languages:** " + " · ".join(entries)


def front_matter(code: str, spec: dict) -> str:
    """The docs-site header for a translation, written in the reader's language.

    `title` and `description` are what a search engine shows in a result, so they
    have to be in the language the page is written in — an English title on a
    Persian page is the pair Google shows to nobody. Both come from the locale's
    own strings rather than a template.

    `alternates` is the whole point of the move: `hooks/hreflang.py` turns this one
    declaration into reciprocal `hreflang` tags on both this page and the English
    front page. Without it the 28 translations read as unrelated duplicates.
    """
    t = spec["strings"]
    description = " ".join(t["pitch"].split())
    return (
        "---\n"
        f'title: "YazSes — {spec["name"]}"\n'
        f'description: "{description}"\n'
        "alternates:\n"
        "  en: index.md\n"
        "---\n"
    )


def render(code: str, spec: dict, sha: str) -> str:
    t = spec["strings"]
    rtl = spec.get("rtl", False)
    wall = contributors_block()
    body = f"""{switcher(code)}
<!-- yazses-l10n: locale={code}; source=README.md; source_sha={sha}; scope=partial; status=draft -->

> ⚠️ **{t['draft_title']}** — {t['draft_body']}
>
> *This is a machine-assisted **draft** translation, not yet reviewed by a native
> speaker. English is authoritative: [README.md]({ENGLISH_README}). Improving it is a
> welcome first contribution — see [issue #{spec['issue']}](https://github.com/MSKazemi/yazses/issues/{spec['issue']}).*

# YazSes

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
- [{t['link_readme']}]({ENGLISH_README})
- [{t['link_issues']}](https://github.com/MSKazemi/yazses/issues)

---

## Contributors

{wall}
"""
    if rtl:
        # The switcher stays the first line of the body, so it goes ABOVE the wrapper
        # rather than inside it — the switcher is language-neutral and the checker
        # looks for it before any prose. Everything after it is right-to-left.
        first, rest = body.split("\n", 1)
        body = f'{first}\n\n<div dir="rtl">\n\n{rest}\n</div>\n'
    # Front matter is prepended last, after any RTL wrapping: it is YAML the docs
    # build parses, not prose, and wrapping it in a `dir="rtl"` div would leave the
    # page with no title, description or `alternates` at all.
    return front_matter(code, spec) + "\n" + body


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
        f"[docs/{code}/index.md](https://mskazemi.com/yazses/{code}/index.html) | "
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
        path = translation_path(code)
        rel = path.relative_to(ROOT).as_posix()
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                problems.append(rel)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {rel}")

    # Every existing README's switcher must list the new locales too, or their
    # links go stale the moment a language is added.
    if not args.check:
        targets = [(ROOT / "README.md", "en")]
        targets += [(translation_path(code), code) for code in HUMAN_LOCALES]
        for path, current in targets:
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            # Not line 0 any more — a translation now opens with docs-site front
            # matter, so the switcher has to be found rather than assumed.
            for i, line in enumerate(lines):
                if line.startswith("**Read this in other languages:**"):
                    lines[i] = switcher(current) + "\n"
                    path.write_text("".join(lines), encoding="utf-8")
                    print(f"updated switcher in {path.relative_to(ROOT).as_posix()}")
                    break

    if not args.check:
        _update_status_page(sha)

    if problems:
        print("out of date: " + ", ".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
