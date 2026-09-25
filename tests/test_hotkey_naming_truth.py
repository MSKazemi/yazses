"""Nothing a user reads may name a hold-to-talk key the daemon would not bind.

`[hotkey] key` defaults to `"auto"`, and first-run seeding never writes a hotkey, so
what a brand-new install actually binds is `platform.default_hotkey` — `right_alt` on
Linux and FreeBSD, `right_option` on macOS, `right_ctrl` on Windows. A modifier was
chosen on purpose, "so it never collides with normal typing the way the space bar
would" (`config.py`).

The surfaces did not all say so. This was found and fixed once before, in the README's
first table and the docs home page, and that fix was described in the CHANGELOG as
covering "four places". It named the four by hand — and a hand-written list of sites is
the defect, not the fix. Every install path was missed, so for months the *first screen
of the installer* still said:

    Hold Space → speak → release → text appears anywhere

which is the single worst place to be wrong. It is the first thing a new user does: they
hold Space, nothing happens, and the reasonable conclusion is that YazSes is broken. The
`.deb` `Description:` field said it too, so apt and every software centre repeated it.

So this file replaces the hand-written list with a scan, and replaces the hand-typed
answer with the code's. The truth is read straight out of each `platform/<os>/__init__.py`
by AST — no literal key name is typed here, so adding an OS or changing a default moves
this guard with it rather than leaving it asserting yesterday's answer.

Two rules, both deliberately narrow — a guard is judged on how rarely it fires
(ADR-021), and on the tree as it stands these two find 9 violations and 0 false alarms
while validating 27 correct OS/key pairings:

1. **An unqualified "hold X" must name some platform's default.** `Space` is nobody's
   default, so it fails anywhere. `right_ctrl` is Windows's, so a transcript of doctor
   output or a `yazses hotkey set right_ctrl` example does not fire.
2. **Where a line pairs an OS with a key, the pair must be right.** Only *adjacent*
   pairings count — `Right Alt on Linux`, `| Linux | `Right Alt` |`,
   `hotkey on Linux: **Right Alt**`. A sentence that correctly lists all three
   (`Right Alt on Linux, Right Option on macOS, Right Ctrl on Windows`) yields three
   correct pairs, not nine mismatched ones.

`CHANGELOG.md` and `docs/releases/` are excluded: they are immutable records that quote
the old wrong text on purpose, and a guard that demanded they be edited would be asking
for history to be rewritten.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

from yazses.hotkeys.names import SUPPORTED_HOTKEYS, canonical

ROOT = Path(__file__).resolve().parent.parent
PLATFORM_PACKAGES = ROOT / "src" / "yazses" / "platform"

#: How each platform package's OS is spelled in prose. Not a list of keys — the keys
#: come from the code below — but the package name `macos` never appears in a sentence.
#: `test_every_platform_default_has_a_spelling` proves this covers every platform that
#: declares a default, so adding an OS fails here rather than going unchecked.
OS_SPELLINGS: dict[str, str] = {
    "linux": r"Linux",
    "macos": r"macOS|Mac ?OS|OS X",
    "windows": r"Windows",
    "bsd": r"(?:Free|Open|Net)?BSD",
}

#: Trees that are not user-facing prose, plus the two that are immutable history.
SKIP_DIRS = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", "site", "src", "tests", "fuzz",
     ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
SKIP_FILES = frozenset({"CHANGELOG.md"})
SKIP_PREFIXES = (("docs", "releases"),)
BINARY_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".woff", ".woff2",
     ".lock", ".gz", ".zip", ".pdf", ".mp4", ".wav", ".onnx", ".bin"}
)


def _platform_defaults() -> dict[str, str]:
    """`{"linux": "right_alt", ...}`, read out of the source without importing it.

    `default_hotkey` is a keyword to the `Platform(...)` call inside `build_platform()`,
    which imports that OS's backends — unimportable on the other three. AST is how a
    Linux test run gets to read the Windows answer.
    """
    found: dict[str, str] = {}
    for package in sorted(PLATFORM_PACKAGES.iterdir()):
        init = package / "__init__.py"
        if not package.is_dir() or not init.exists():
            continue
        # A file we cannot parse must fail the run, not quietly report compliance.
        tree = ast.parse(init.read_text(encoding="utf-8"), filename=str(init))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "default_hotkey" and isinstance(keyword.value, ast.Constant):
                    found[package.name] = str(keyword.value.value)
    return found


DEFAULTS = _platform_defaults()
DEFAULT_IDS = frozenset(canonical(key) for key in DEFAULTS.values())

_KEY = "|".join(
    sorted((key.replace("_", r"[ _-]?") for key in SUPPORTED_HOTKEYS), key=len, reverse=True)
)
_OS = "|".join(OS_SPELLINGS.values())
_MARKUP = r"[`*_ ]{0,3}"

#: "Hold Right Alt", "hold down the space bar" — an imperative naming a key.
HOLD_RE = re.compile(rf"\bhold(?:ing)?\s+(?:down\s+)?(?:the\s+)?{_MARKUP}(?P<key>{_KEY})\b", re.I)
#: "Right Alt on Linux"
KEY_ON_OS_RE = re.compile(rf"\b(?P<key>{_KEY})\b{_MARKUP}\s+(?:on|for)\s+{_MARKUP}(?P<os>{_OS})\b",
                          re.I)
#: "Linux: **Right Alt**" and the table row "| Linux | `Right Alt` |"
OS_THEN_KEY_RE = re.compile(rf"\b(?P<os>{_OS})\b\s*[:|]\s*{_MARKUP}(?P<key>{_KEY})\b", re.I)


class Mention(NamedTuple):
    where: str
    line: str
    key: str
    os: str  # "" when the mention names no OS


def _key_id(spelled: str) -> str:
    """`Right-Alt` / `right alt` / `Right Option` -> the id the platform layer uses."""
    return canonical(re.sub(r"[ \-]", "_", spelled).lower())


def _os_key(spelled: str) -> str:
    for package, pattern in OS_SPELLINGS.items():
        if re.fullmatch(pattern, spelled.strip(), re.I):
            return package
    return ""


def _tracked(root: Path) -> list[str]:
    """The files this project actually ships, asked of git rather than of the disk.

    Walking the tree instead reads whatever the developer happens to have lying
    around: `.claude/` session notes, a private `strategy/` tree, a built `site/`.
    Two of those are ignored *because* they are local or private, and one run of
    this guard flagged a plan file that was quoting the bug in order to describe
    it -- a guard that fires on the maintainer's own notes is a guard people learn
    to dismiss. `git ls-files` is also the honest definition of a surface: if it
    is not committed, no user can read it.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root, capture_output=True, check=True, text=True,
    )
    return [name for name in out.stdout.split("\0") if name]


def _surfaces(root: Path) -> list[tuple[str, str]]:
    """Every user-facing text file this project ships, as `(path, contents)`."""
    out: list[tuple[str, str]] = []
    for name in sorted(_tracked(root)):
        rel = Path(name)
        if set(rel.parts) & SKIP_DIRS or str(rel) in SKIP_FILES:
            continue
        if any(rel.parts[: len(prefix)] == prefix for prefix in SKIP_PREFIXES):
            continue
        if rel.suffix.lower() in BINARY_SUFFIXES:
            continue
        path = root / rel
        if not path.is_file():
            continue
        try:
            out.append((rel.as_posix(), path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue
    return out


def hold_instructions(root: Path) -> list[Mention]:
    """Every "hold <key>" a reader could act on."""
    return [
        Mention(f"{rel}:{n}", line.strip(), match.group("key"), "")
        for rel, text in _surfaces(root)
        for n, line in enumerate(text.splitlines(), 1)
        for match in HOLD_RE.finditer(line)
    ]


def os_pairings(root: Path) -> list[Mention]:
    """Every place a line pairs an OS with a key name."""
    found: list[Mention] = []
    for rel, text in _surfaces(root):
        for n, line in enumerate(text.splitlines(), 1):
            for pattern in (KEY_ON_OS_RE, OS_THEN_KEY_RE):
                for match in pattern.finditer(line):
                    package = _os_key(match.group("os"))
                    if package in DEFAULTS:
                        found.append(Mention(f"{rel}:{n}", line.strip(), match.group("key"),
                                             package))
    return found


# --------------------------------------------------------------------------- guard the guard


def test_the_platform_defaults_were_actually_read():
    """Every rule below compares against `DEFAULTS`. Empty, they all pass vacuously."""
    assert {"linux", "macos", "windows"} <= set(DEFAULTS), (
        f"could not read `default_hotkey` out of the platform packages; got {DEFAULTS}. "
        f"If `Platform(...)` stopped taking it as a literal keyword, this parser needs "
        f"updating — it is the only thing standing between a user and a key that does nothing."
    )


def test_every_platform_default_has_a_spelling():
    """A new OS must be added to `OS_SPELLINGS`, not silently skipped by the pairing rule."""
    unspelled = sorted(set(DEFAULTS) - set(OS_SPELLINGS))
    assert not unspelled, (
        f"{unspelled} declare a `default_hotkey` but have no prose spelling, so no "
        f"documentation naming them would ever be checked. Add them to OS_SPELLINGS."
    )


def test_the_scan_finds_something_to_check():
    """A scan that matches nothing reports compliance for free.

    Both rules are "every match must be right". On an empty match set that is trivially
    true, so a regex that silently stopped matching — or a `_surfaces` walk that stopped
    finding files — would turn this whole module green and useless.
    """
    assert hold_instructions(ROOT), "no 'hold <key>' instruction found anywhere; HOLD_RE is dead"
    assert os_pairings(ROOT), "no OS/key pairing found anywhere; the pairing patterns are dead"


def test_an_empty_tree_yields_no_matches(tmp_path):
    """The other half of that: prove an empty set is what emptiness produces.

    `test_the_scan_finds_something_to_check` is only meaningful if the collectors can in
    fact come back empty — which is exactly what they do on a tree with no surfaces in it.

    The tree is a real repository because the collector asks git what is tracked, not
    the filesystem. Staging the file is enough; `git ls-files` reads the index.
    """
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "nothing.md").write_text("No keys are named here.\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "docs/nothing.md"], cwd=tmp_path, check=True)
    assert _surfaces(tmp_path), "the fixture staged nothing; this would pass for free"
    assert hold_instructions(tmp_path) == []
    assert os_pairings(tmp_path) == []


def test_a_tree_git_cannot_read_fails_rather_than_reporting_compliance(tmp_path):
    """An unreadable input must be an error, never an empty, clean-looking result.

    The collector used to walk the filesystem, so "no repository here" and "nothing
    to flag" were the same answer. They are not the same fact.
    """
    with pytest.raises(subprocess.CalledProcessError):
        _surfaces(tmp_path)


# --------------------------------------------------------------------------- the rules


def test_no_surface_tells_a_user_to_hold_a_key_that_is_nobody_s_default():
    """"Hold Space" is wrong on every OS YazSes supports, and it shipped in the installers.

    A key that *is* some platform's default passes here even unqualified: a doctor
    transcript in the troubleshooting guide, or a `yazses hotkey set right_ctrl` example
    showing its own effect, is not a claim about what a fresh install binds.
    """
    wrong = [m for m in hold_instructions(ROOT) if _key_id(m.key) not in DEFAULT_IDS]
    assert not wrong, "a user following these would hold a key that does nothing:\n" + "\n".join(
        f"  {m.where}: names {m.key!r}, but no platform defaults to it "
        f"(defaults: {sorted(set(DEFAULTS.values()))})\n    {m.line[:100]}"
        for m in wrong
    )


def test_every_os_specific_key_claim_names_that_platform_s_default():
    """A per-OS table or sentence must match that OS's `default_hotkey`, not another's."""
    wrong = [m for m in os_pairings(ROOT) if _key_id(m.key) != canonical(DEFAULTS[m.os])]
    assert not wrong, "these pair an OS with the wrong hold-to-talk key:\n" + "\n".join(
        f"  {m.where}: says {m.key!r} for {m.os}, which defaults to {DEFAULTS[m.os]!r}\n"
        f"    {m.line[:100]}"
        for m in wrong
    )
