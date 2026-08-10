#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=11.3.0"]
# ///
"""Render real terminal output as a publication-quality PNG.

A screenshot of a terminal is a photograph of a moment on one machine: it carries
that machine's home directory, its window theme, and whatever version happened to
be installed. This renders the *text* instead, in the YazSes identity (#0d1117 /
#3fb950) already used by the og-card — so a published still is reproducible, stays
in one visual language, and never leaks a local directory layout.

    yazses doctor | uv run scripts/render-term.py "yazses doctor" \\
        docs/screenshots/yazses-doctor.png

    # include the prompt line, the way the committed screenshot has it
    { echo '$ yazses doctor'; yazses doctor; } | uv run scripts/render-term.py \\
        "yazses doctor — all systems go" docs/screenshots/yazses-doctor.png

Re-run it after a release: a stale version number on the screenshot that exists to
prove the install works is worse than having no screenshot at all.

Like `record-demo.py`, this resolves its one dependency into uv's cache — nothing
is installed system-wide and nothing joins the project's dependency tree.
"""
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG      = (13, 17, 23)        # #0d1117
CHROME  = (22, 27, 34)        # #161b22
BORDER  = (48, 54, 61)        # #30363d
TEXT    = (230, 237, 243)     # #e6edf3
DIM     = (139, 148, 158)     # #8b949e
GREEN   = (63, 185, 80)       # #3fb950
RED     = (248, 81, 73)
YELLOW  = (210, 153, 34)

# The renderer needs a real monospace TTF: Pillow's built-in bitmap font has no
# metrics to lay a terminal out with. DejaVu is the Linux default; the rest are the
# usual macOS/Windows equivalents, so this works off a stock install anywhere.
_MONO_CANDIDATES = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSansMono.ttf",
     "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf"),
    ("/Library/Fonts/Menlo.ttc", "/Library/Fonts/Menlo.ttc"),
    ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Menlo.ttc"),
    ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/consolab.ttf"),
)


def _find_mono() -> tuple[str, str]:
    for regular, bold in _MONO_CANDIDATES:
        if Path(regular).exists() and Path(bold).exists():
            return regular, bold
    sys.exit(
        "No monospace TTF found. Install one (Debian/Ubuntu: "
        "`sudo apt install fonts-dejavu-core`) or add its path to _MONO_CANDIDATES."
    )


MONO, MONO_BOLD = _find_mono()

SCALE = 2                     # render 2x, downsample -> crisp text
FS    = 15 * SCALE
PAD   = 22 * SCALE
BAR_H = 38 * SCALE
LEAD  = int(FS * 1.52)

HOME = str(Path.home())


# A terminal wraps; a canvas sized from the longest line does not. One pathological
# line (`yazses status` can carry a whole failed argv in `last err:`) otherwise
# produces an image tens of thousands of pixels wide that no viewer will render.
MAX_COLS = 120


def sanitize(line: str) -> str:
    """Never publish a local directory layout, and never let one line size the canvas."""
    line = line.replace(HOME, "~").rstrip("\n")
    if len(line) > MAX_COLS:
        line = line[: MAX_COLS - 1] + "…"
    return line


def colour_for(line: str):
    """Colour a line the way the terminal actually shows it."""
    s = line.strip()
    if s.startswith("[OK]"):
        return GREEN
    if s.startswith(("[FAIL]", "[ERROR]", "[MISSING]")):
        return RED
    if s.startswith(("[WARN]", "[SKIP]")):
        return YELLOW
    if s.startswith("✓"):
        return GREEN
    if s.startswith("$"):
        return TEXT
    if re.match(r"^[╭╰│─╮╯]", s):
        return DIM
    return TEXT


def render(title: str, lines, out: Path):
    lines = [sanitize(l) for l in lines]
    # drop trailing blanks
    while lines and not lines[-1].strip():
        lines.pop()

    f = ImageFont.truetype(MONO, FS)
    fb = ImageFont.truetype(MONO_BOLD, FS)

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    cw = probe.textlength("M", font=f)
    width_chars = max((len(l) for l in lines), default=40)
    W = int(cw * width_chars) + PAD * 2
    W = max(W, 640 * SCALE)
    H = BAR_H + PAD * 2 + LEAD * len(lines)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # title bar + traffic lights
    d.rectangle([0, 0, W, BAR_H], fill=CHROME)
    d.line([(0, BAR_H), (W, BAR_H)], fill=BORDER, width=SCALE)
    r = 5 * SCALE
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = PAD + i * (r * 3.2) + r
        d.ellipse([cx - r, BAR_H / 2 - r, cx + r, BAR_H / 2 + r], fill=c)
    d.text((PAD + r * 11, BAR_H / 2 - FS * 0.62), title, font=f, fill=DIM)

    y = BAR_H + PAD
    for line in lines:
        # "$ cmd" prompt gets a green sigil
        if line.startswith("$ "):
            d.text((PAD, y), "$", font=fb, fill=GREEN)
            d.text((PAD + cw * 2, y), line[2:], font=fb, fill=TEXT)
        else:
            col = colour_for(line)
            if col is GREEN and line.strip().startswith("[OK]"):
                i = line.index("[OK]")
                d.text((PAD, y), line[:i], font=f, fill=DIM)
                d.text((PAD + cw * i, y), "[OK]", font=fb, fill=GREEN)
                d.text((PAD + cw * (i + 4), y), line[i + 4:], font=f, fill=TEXT)
            else:
                d.text((PAD, y), line, font=f, fill=col)
        y += LEAD

    d.rectangle([0, 0, W - 1, H - 1], outline=BORDER, width=SCALE)
    img = img.resize((W // SCALE, H // SCALE), Image.LANCZOS)
    img.save(out)
    print(f"  {out.name:38s} {img.size[0]}x{img.size[1]}  {out.stat().st_size//1024} KB")


if __name__ == "__main__":
    title = sys.argv[1] if len(sys.argv) > 1 else "terminal"
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "out.png")
    render(title, sys.stdin.read().splitlines(), out)
