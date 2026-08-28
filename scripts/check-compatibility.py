#!/usr/bin/env python3
"""Validate community setup reports in `SHOWCASE.md`.

    uv run python scripts/check-compatibility.py            # every entry
    uv run python scripts/check-compatibility.py --new-only # only entries you added

A setup report is only worth having if it says which environment it describes. "It works"
with no OS, no desktop session and no microphone is a nice sentence and useless evidence —
X11 and Wayland behave differently enough that a report which omits the session cannot be
acted on.

It also refuses an entry containing a home path, an email or a token. People paste
`yazses doctor` output into these, and that output contains their username.

This deliberately checks *shape*, never truth. Whether the report is honest is a human
judgement and stays one.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from campaign_preflight import scan_personal_data  # noqa: E402

SHOWCASE = ROOT / "SHOWCASE.md"

#: The fields the template asks for. A report missing the session (X11 vs Wayland) or the
#: microphone cannot be compared against another machine.
REQUIRED_FIELDS = ("OS / desktop", "Mic", "Apps you dictate into", "How you use YazSes")

#: X11 and Wayland are Linux/BSD display servers. Windows and macOS have neither, so
#: asking those entries to name one rejects a *correct* report -- which is exactly what
#: happened on the day the first Windows and macOS setups arrived, on a project whose
#: scarcest evidence is Windows and macOS testing. The session question is put only to
#: the platforms that can answer it; the requirement itself is unchanged for Linux.
SESSIONLESS_OS_RE = re.compile(r"\b(windows|macos|mac ?os ?x?|osx|darwin)\b", re.I)

ENTRY_RE = re.compile(r"^###\s+(.+?)\s*$", re.M)
#: The instructions contain a fenced template that looks exactly like a real entry.
FENCE_RE = re.compile(r"```.*?```", re.S)


def entries(markdown: str) -> list[tuple[str, str]]:
    """(heading, body) for each `### ` block, ignoring the fenced template."""
    without_templates = FENCE_RE.sub("", markdown)
    found = list(ENTRY_RE.finditer(without_templates))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(without_templates)
        out.append((m.group(1), without_templates[m.end():end]))
    return out


def check_entry(heading: str, body: str) -> list[str]:
    """Every problem with one setup report."""
    problems: list[str] = []
    if heading.startswith("<") or "your name" in heading.lower():
        return [f"{heading!r}: looks like the unfilled template — replace the placeholder"]

    for field in REQUIRED_FIELDS:
        if f"**{field}:**" not in body:
            problems.append(
                f"{heading}: missing **{field}:** — without it this report cannot be "
                "compared against another machine"
            )

    session = re.search(r"\*\*OS / desktop:\*\*(.*)", body)
    if (
        session
        and not SESSIONLESS_OS_RE.search(session.group(1))
        and not re.search(r"\b(x11|wayland)\b", session.group(1), re.I)
    ):
        problems.append(
            f"{heading}: the OS/desktop line does not say X11 or Wayland. They behave "
            "differently enough that a report omitting it cannot be acted on."
        )

    for label, snippet, hint in scan_personal_data(body):
        problems.append(f"{heading}: {label} — {snippet} — {hint}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=SHOWCASE)
    args = ap.parse_args(argv)

    found = entries(args.file.read_text(encoding="utf-8"))
    problems = [p for heading, body in found for p in check_entry(heading, body)]

    if problems:
        print(f"✗ {len(problems)} problem(s) across {len(found)} entries:\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"✓ {len(found)} setup report(s) valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
