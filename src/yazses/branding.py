"""Author, contact, and project links — the single source of truth surfaced in
the running app (``yazses about``, ``yazses quickstart``, the ``--help`` epilog,
and ``yazses doctor``).

Keep these in step with ``pyproject.toml`` ([project] authors) and
``snap/snapcraft.yaml`` (contact / website / source-code / issues) so every
distribution channel points people at the same author and the same place to
report issues or request features.

The banner draws the same mark as ``docs/assets/logo.svg`` — a "Y" over a
listening sound-wave — so the terminal is the same identity as the docs site,
the Snap Store listing, and the tray badge rather than a fifth unrelated one.
Everything degrades: truecolor → 256-colour → no colour, and Unicode blocks →
plain ASCII when the terminal's codepage cannot encode them.
"""

from __future__ import annotations

import math
import os
import re
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Callable, Iterable, Sequence, TextIO

APP_NAME = "YazSes"
TAGLINE = "Local, offline-by-default voice dictation — hold a key, speak, release."

# Brand gradient, lifted from docs/assets/favicon.svg's linearGradient stops.
# Swept diagonally (x1,y1 -> x2,y2) across the mark, matching the SVG.
BRAND_TOP = (0x7C, 0x4D, 0xFF)
BRAND_BOTTOM = (0x45, 0x27, 0xA0)

# The logo as terminal art: the "Y" strokes, the stem, then the sound-wave.
# Unicode block elements read best, so they are the preferred form...
MARK_ART = [
    r"    ╲       ╱",
    r"     ╲     ╱",
    r"      ╲   ╱",
    r"       ╲ ╱",
    r"        │",
    "   ▁▂▃▅▇█▇▅▃▂▁",
]
# ...but a legacy Windows console on cp437, or any non-UTF-8 codepage, cannot
# encode them. This form is pure ASCII and is chosen automatically (see
# _can_encode); the shape has to survive, not the exact glyphs.
MARK_ART_ASCII = [
    r"    \       /",
    r"     \     /",
    r"      \   /",
    r"       \ /",
    r"        |",
    r"   .-=+*#*+=-.",
]

# Kept as the documented name for "the art the banner draws". Tests and any
# other caller should read this rather than hard-coding glyphs.
BANNER_ART = "\n".join(MARK_ART)

# Ramp used by the resting wave and the `quickstart` ripple, quietest first.
_WAVE_RAMP = "▁▂▃▄▅▆▇█"
# The resting sound-wave as levels into _WAVE_RAMP — the shape the ripple
# settles onto, so the animation lands exactly on the logo.
_WAVE_REST = (0, 1, 2, 4, 6, 7, 6, 4, 2, 1, 0)

# Columns between the mark and the text block beside it.
_GUTTER = 6

# SGR colour escapes, stripped when measuring how wide a row actually draws.
_SGR_RE = re.compile(r"\033\[[0-9;]*m")

AUTHOR = "Mohsen Seyedkazemi Ardebili"
EMAIL = "mohsen.seyedkazemi@gmail.com"

WEBSITE = "https://mskazemi.com/yazses/"
SOURCE = "https://github.com/MSKazemi/yazses"
ISSUES = "https://github.com/MSKazemi/yazses/issues"
# Where to propose a new feature — GitHub Discussions if enabled, otherwise a
# labelled issue works just as well.
FEATURES = "https://github.com/MSKazemi/yazses/issues/new"


def version() -> str:
    """Installed package version, or ``dev`` when running from a source tree
    without an installed distribution."""
    try:
        return _pkg_version("yazses")
    except PackageNotFoundError:
        return "dev"


def _supports_banner() -> bool:
    """True when the banner art should be drawn: an interactive stdout and
    NO_COLOR not requested. False in pipes, redirects, or plain-output mode so the
    art never garbles logs or non-UTF-8 captures."""
    if os.environ.get("NO_COLOR"):
        return False
    from yazses.system import streams

    return streams.stdout_isatty()


# --------------------------------------------------------------------------
# Colour ladder
# --------------------------------------------------------------------------

def color_depth(stream: TextIO | None = None) -> str:
    """How much colour this terminal can actually show: ``truecolor``, ``256``
    or ``mono``.

    Delegates the detection to ``rich`` — a hard dependency of Typer, so it is
    always present — rather than re-deriving it from ``TERM``/``COLORTERM``.
    Rich already handles the cases that hand-rolled checks get wrong: Windows
    conhost via colorama, dumb terminals, and CI. Any failure degrades to
    ``mono``, because a banner is never worth an exception.
    """
    if os.environ.get("NO_COLOR"):
        return "mono"
    try:
        from rich.console import Console

        system = Console(file=stream or sys.stdout).color_system
    except Exception:
        return "mono"
    if system == "truecolor":
        return "truecolor"
    if system in ("256", "standard", "windows"):
        return "256"
    return "mono"


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Blend two RGB triples; ``t`` is clamped to [0, 1]."""
    t = min(1.0, max(0.0, t))
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def _rgb_to_256(rgb: tuple[int, int, int]) -> int:
    """Nearest xterm-256 index from the 6x6x6 colour cube."""
    r, g, b = (min(5, round(c / 255 * 5)) for c in rgb)
    return 16 + 36 * r + 6 * g + b


def _ansi(rgb: tuple[int, int, int], depth: str) -> str:
    """SGR foreground escape for ``rgb`` at the given depth (empty for mono)."""
    if depth == "truecolor":
        return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"
    if depth == "256":
        return f"\033[38;5;{_rgb_to_256(rgb)}m"
    return ""


def colorize_mark(lines: Sequence[str], depth: str) -> list[str]:
    """Sweep the brand gradient diagonally across the mark, one colour per
    character — the direction favicon.svg uses, which is what makes it read as
    designed rather than as a per-row rainbow.

    Returned unchanged at ``mono``. Only the art is ever coloured; the text
    beside it stays terminal-default, so it keeps its contrast on a light theme
    and stays greppable for anything reading our output.
    """
    if depth == "mono":
        return list(lines)
    height = max(len(lines) - 1, 1)
    width = max(max((len(ln) for ln in lines), default=1) - 1, 1)
    out: list[str] = []
    for y, line in enumerate(lines):
        buf = ""
        for x, ch in enumerate(line):
            if ch == " ":
                buf += " "
                continue
            buf += _ansi(_lerp(BRAND_TOP, BRAND_BOTTOM, (x / width + y / height) / 2), depth) + ch
        out.append(buf + "\033[0m" if buf.strip() else buf)
    return out


def _can_encode(text: str, stream: TextIO | None = None) -> bool:
    """True when the terminal's encoding can actually represent ``text``.

    A legacy Windows console on cp437 raises (or mojibakes) on block elements,
    so the Unicode mark is only used where it will survive the round-trip.
    """
    encoding = getattr(stream or sys.stdout, "encoding", None) or "ascii"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def mark_lines(*, unicode_ok: bool | None = None, stream: TextIO | None = None) -> list[str]:
    """The mark art in the richest form this terminal can encode."""
    if unicode_ok is None:
        unicode_ok = _can_encode("".join(MARK_ART), stream)
    return list(MARK_ART if unicode_ok else MARK_ART_ASCII)


# --------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------

# Non-ASCII punctuation that appears in our own copy, and what to write instead
# when the terminal cannot encode it. The tagline's em dash is the reason this
# exists: ASCII art is not enough on its own if the text beside it still can't
# be encoded.
_ASCII_PUNCTUATION = {"—": "-", "–": "-", "·": "*", "“": '"', "”": '"', "’": "'"}


def ascii_safe(text: str) -> str:
    """Rewrite our copy into pure ASCII, preserving meaning."""
    for fancy, plain in _ASCII_PUNCTUATION.items():
        text = text.replace(fancy, plain)
    return text


def _tagline_lines(*, unicode_ok: bool = True) -> list[str]:
    """The tagline split across two rows at its em dash.

    Derived from TAGLINE rather than duplicated, so the banner cannot drift from
    the one-line form used everywhere else.
    """
    head, _, tail = TAGLINE.partition("—")
    lines = [TAGLINE] if not tail else [f"{head.strip()} —", tail.strip()]
    return lines if unicode_ok else [ascii_safe(line) for line in lines]


def visible_width(text: str) -> int:
    """Display columns ``text`` occupies, ignoring SGR colour escapes.

    Padding coloured art with ``str.ljust`` counts every escape byte as a visible
    column, so the pad silently collapses to nothing and each row starts its text
    at a different place. Measure what the terminal draws, not what the string
    holds.
    """
    return len(_SGR_RE.sub("", text))


def compose_banner(
    art: Sequence[str],
    text: Sequence[str],
    *,
    gutter: int = _GUTTER,
    art_width: int | None = None,
) -> list[str]:
    """Lay ``text`` rows out to the right of the ``art`` rows.

    Accepts art that is already coloured and measures it with ``visible_width``,
    so every text row starts in the same column regardless of how many escape
    sequences the gradient injected into that particular row.
    """
    if art_width is None:
        art_width = max((visible_width(ln) for ln in art), default=0)
    rows: list[str] = []
    for i in range(max(len(art), len(text))):
        left = art[i] if i < len(art) else ""
        right = text[i] if i < len(text) else ""
        if not right:
            rows.append(left.rstrip())
            continue
        pad = " " * max(0, art_width - visible_width(left))
        rows.append(f"{left}{pad}{' ' * gutter}{right}".rstrip())
    return rows


def banner_lines(
    *,
    depth: str | None = None,
    unicode_ok: bool | None = None,
    stream: TextIO | None = None,
) -> list[str]:
    """The full banner as rendered rows: the mark, gradient-swept, with the name,
    version and tagline set beside it."""
    if unicode_ok is None:
        unicode_ok = _can_encode("".join(MARK_ART) + TAGLINE, stream)
    art = mark_lines(unicode_ok=unicode_ok, stream=stream)
    art_width = max((len(ln) for ln in art), default=0)
    text = ["", f"{APP_NAME} {version()}", *_tagline_lines(unicode_ok=unicode_ok)]
    colored = colorize_mark(art, depth if depth is not None else color_depth(stream))
    return compose_banner(colored, text, art_width=art_width)


def banner(
    *,
    force: bool | None = None,
    depth: str | None = None,
    unicode_ok: bool | None = None,
    stream: TextIO | None = None,
) -> str:
    """The branded header for ``yazses about`` and ``yazses quickstart``: the
    logo mark + name + version + tagline.

    Falls back to a plain ``APP_NAME vX.Y — TAGLINE`` line when the terminal
    can't show the art (non-TTY / NO_COLOR), so piped or logged output stays
    clean. ``force``/``depth``/``unicode_ok`` override the auto-detection and
    exist so tests can pin every rung of the ladder.
    """
    show_art = _supports_banner() if force is None else force
    if not show_art:
        plain = f"{APP_NAME} {version()} — {TAGLINE}"
        can_encode = _can_encode(plain, stream) if unicode_ok is None else unicode_ok
        return plain if can_encode else ascii_safe(plain)
    return "\n".join(banner_lines(depth=depth, unicode_ok=unicode_ok, stream=stream))


# --------------------------------------------------------------------------
# The `quickstart` ripple
# --------------------------------------------------------------------------

def ripple_frames(count: int = 6, *, unicode_ok: bool = True) -> list[str]:
    """Frames of a sound-wave ripple that settles onto the resting mark.

    Deterministic — a travelling sine blended toward ``_WAVE_REST`` by frame, so
    the last frame *is* the logo's wave row and the animation lands exactly on
    the static banner instead of snapping to it. Returns a single resting frame
    when the terminal has no Unicode blocks to animate with.
    """
    rest = "".join(_WAVE_RAMP[level] for level in _WAVE_REST)
    if not unicode_ok or count < 1:
        return [rest]
    if count == 1:
        return [rest]
    frames: list[str] = []
    span = len(_WAVE_REST)
    for f in range(count):
        t = f / (count - 1)
        row = ""
        for i in range(span):
            travel = (math.sin(i * 0.9 + f * 0.8) * 0.5 + 0.5) * (len(_WAVE_RAMP) - 1)
            level = round((1 - t) * travel + t * _WAVE_REST[i])
            row += _WAVE_RAMP[min(len(_WAVE_RAMP) - 1, max(0, level))]
        frames.append(row)
    return frames


def should_animate(stream: TextIO | None = None) -> bool:
    """True only where an animation is welcome and harmless.

    Deliberately narrow: an interactive stdout, colour not refused, and not CI.
    Every non-interactive consumer — pipes, logs, CI, ``NO_COLOR`` — gets the
    static banner, because a wave that redraws itself is noise in a transcript.
    """
    if os.environ.get("CI"):
        return False
    if not _supports_banner():
        return False
    if not _can_encode("".join(MARK_ART), stream):
        return False
    return color_depth(stream) != "mono"


def play_ripple(
    *,
    write: Callable[[str], None],
    sleep: Callable[[float], None],
    frames: Iterable[str] | None = None,
    depth: str = "truecolor",
    interval: float = 0.07,
    indent: str = "   ",
) -> None:
    """Draw the ripple in place, one frame per ``interval``.

    ``write`` and ``sleep`` are injected so the whole animation is testable
    without a terminal or a real delay. Each frame is rewritten over the last
    with a carriage return, so it occupies one line and leaves the cursor at the
    start of it — the caller then prints the static banner over the top.
    """
    seq = list(frames if frames is not None else ripple_frames())
    lead = _ansi(_lerp(BRAND_TOP, BRAND_BOTTOM, 0.5), depth)
    reset = "\033[0m" if lead else ""
    for i, frame in enumerate(seq):
        write(f"\r{indent}{lead}{frame}{reset}")
        if i < len(seq) - 1:
            sleep(interval)
    write("\r\033[2K" if lead else "\r")


def contact_lines() -> list[str]:
    """Plain ``label: value`` lines for author + contact, reused by ``doctor``
    and any other plaintext surface."""
    return [
        f"Author:   {AUTHOR} <{EMAIL}>",
        f"Website:  {WEBSITE}",
        f"Source:   {SOURCE}",
        f"Issues:   {ISSUES}",
        f"Features: {FEATURES}",
    ]
