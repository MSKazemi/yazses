"""No shipped surface may tell a user to install the YazSes VS Code extension.

There is no such extension. There is no source for it in this repository, no marketplace
listing, no publish workflow, and every design note that mentions it (adr-v04-002,
gap-002) calls it a deferred, separately shipped artefact. Five surfaces nevertheless
instructed the user to install it: the `yazses jump` failure message, two
`LspContextProvider` log lines, `docs/features.md` and `docs/privacy-statement.md`.

A user who follows that instruction searches the marketplace, finds nothing, and
concludes YazSes is broken or that they have missed a step. For `jump` it was worse than
unhelpful: `VSCodeBridge.get_symbols` returns `{}` and `apply_motion` returns `False`,
and `jump` calls both, so an extension would not have made the command work either.

`design/` is deliberately out of scope — a design note *may* discuss an artefact it
proposes building, and calling it deferred there is the honest thing to do. What may not
happen is a shipped surface stating it as available.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIPPED = sorted((ROOT / "src" / "yazses").rglob("*.py")) + sorted((ROOT / "docs").rglob("*.md"))

# Matches the imperative ("install the … extension") and the offer-as-an-alternative
# ("or the VS Code extension"), which is the form docs/features.md used. Both read to a
# user as "this is available to you".
PHANTOM = re.compile(
    r"install(?:ing)?\s+(?:the\s+)?(?:YazSes\s+)?VS\s?Code\s+extension"
    r"|or\s+the\s+VS\s?Code\s+extension"
    r"|If\s+you\s+use\s+the\s+YazSes\s+VS\s?Code\s+extension",
    re.IGNORECASE,
)


def test_the_guard_actually_reads_the_shipped_surfaces():
    """A scan over an empty file list passes vacuously; prove it found the tree."""
    assert len(SHIPPED) > 100, f"only found {len(SHIPPED)} shipped files"
    assert any(p.name == "cli.py" for p in SHIPPED)
    assert any(p.name == "features.md" for p in SHIPPED)


def test_no_shipped_surface_offers_the_vscode_extension():
    offenders = []
    for path in SHIPPED:
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), start=1):
            if PHANTOM.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")

    assert not offenders, (
        "These tell the user to install a VS Code extension that does not exist:\n  "
        + "\n  ".join(offenders)
    )


def test_the_pattern_catches_the_wording_that_was_there():
    """Guards the guard: a regex that matches nothing would pass the test above."""
    for wording in (
        "or install the YazSes VS Code extension.",
        "Install the YazSes VS Code extension. Context injection disabled.",
        "Needs Neovim started with `nvim --listen`, or the VS Code extension.",
        "If you use the YazSes VS Code extension, it also writes `vscode-context.json`",
        "set $NVIM or install the VS Code extension",
    ):
        assert PHANTOM.search(wording), wording
