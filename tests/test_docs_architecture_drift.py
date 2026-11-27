"""Hand-written facts in the architecture pages and the CLI reference, held to the code.

Each check below pins a statement that had drifted:

* `design/architecture.md`'s configuration reference printed `tiny.en`,
  `max_record_seconds = 90`, `[streaming] enabled = true` and a 200 ms pre-speech pad.
  None of those was the shipped default.
* The state diagrams are prose, so a new `TrayState` could appear in the code only.
* The lists of `[injection] backend` values stopped at four of them.
* Shipped options (`start --no-autostart`, `language set --no-download`, the
  `facegesture calibrate` and `gaze measure` options) were absent from the CLI reference.
  `test_docs_flags_exist.py` checks the opposite direction only.
* `yazses features enable gaze` was given as an instruction; an experimental capability
  is refused without `--force`.
* The multilingual "designed" count disagreed with the table directly above it.
"""

from __future__ import annotations

import dataclasses
import re
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import typer.main

from yazses.cli import app
from yazses.config import Config
from yazses.inject.registry import config_values
from yazses.platform.base import TrayState
from yazses.system.features import CAT_LANG, EXPERIMENTAL, feature_status

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DESIGN = ROOT / "design" / "architecture.md"
PUBLIC = DOCS / "architecture.md"
REFERENCE = DOCS / "cli-reference.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _sections(text: str) -> list[str]:
    """Split at `##` and `###` headings, ignoring `#` lines inside code fences."""
    sections: list[list[str]] = [[]]
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(r"#{2,3} ", line):
            sections.append([])
        sections[-1].append(line)
    return ["\n".join(lines) for lines in sections]


def _section(path: Path, heading: str) -> str:
    found = [s for s in _sections(_read(path)) if s.split("\n", 1)[0] == heading]
    assert len(found) == 1, f"expected one {heading!r} heading in {path.name}"
    return found[0]


# --- the configuration reference states the defaults --------------------------


def _wrong_defaults(section: Any, table: dict[str, Any], path: str) -> list[str]:
    wrong: list[str] = []
    for key, shown in table.items():
        name = f"{path}.{key}" if path else key
        if not hasattr(section, key):
            wrong.append(f"{name}: no such key")
            continue
        actual = getattr(section, key)
        if isinstance(shown, dict) and dataclasses.is_dataclass(actual):
            wrong += _wrong_defaults(actual, shown, name)
        elif actual != shown:
            wrong.append(f"{name}: page says {shown!r}, default is {actual!r}")
    return wrong


def test_the_design_configuration_reference_states_the_shipped_defaults() -> None:
    blocks = re.findall(r"```toml\n(.*?)```", _read(DESIGN), re.S)
    assert len(blocks) >= 2, "the configuration blocks were not found"
    wrong: list[str] = []
    for block in blocks:
        wrong += _wrong_defaults(Config(), tomllib.loads(block), "")
    assert not wrong, "design/architecture.md config reference drifted:\n" + "\n".join(wrong)


def test_the_default_check_notices_a_wrong_value() -> None:
    assert _wrong_defaults(Config(), {"audio": {"max_record_seconds": 90}}, "")


# --- states and injection backends are all named ------------------------------


def test_every_daemon_state_is_named_in_both_architecture_pages() -> None:
    pages = {
        "design/architecture.md": _section(DESIGN, "### System overview"),
        "docs/architecture.md": _section(PUBLIC, "## The daemon and its states"),
    }
    for name, text in pages.items():
        missing = [s.name for s in TrayState if not re.search(rf"\b{s.name}\b", text)]
        assert not missing, f"{name} does not name the daemon state(s) {missing}"


def test_every_injection_backend_value_is_listed() -> None:
    values = ("auto", *config_values())
    design_line = next(
        line for line in _read(DESIGN).splitlines() if line.startswith('backend = "auto"')
    )
    pages = {
        "docs/architecture.md": _section(PUBLIC, "## Text injection backends"),
        "docs/cli-reference.md": _section(REFERENCE, "### Choosing the injection backend"),
        "design/architecture.md": design_line,
    }
    for name, text in pages.items():
        missing = [v for v in values if not re.search(rf"\b{v}\b", text)]
        assert not missing, f"{name} lists the [injection] backends without {missing}"


# --- every shipped option is in the CLI reference -----------------------------


def _shipped_options() -> list[tuple[str, tuple[str, ...]]]:
    """`(command path, long spellings)` for every visible option of every command."""
    found: list[tuple[str, tuple[str, ...]]] = []

    def walk(command: Any, path: str) -> None:
        # Duck-typed: a TyperGroup is not a click.Group under Click 8.4.
        for name, sub in (getattr(command, "commands", {}) or {}).items():
            if not getattr(sub, "hidden", False):
                walk(sub, f"{path} {name}".strip())
        if not path:
            return  # the root's --version and completion options are in the intro
        for param in command.params:
            if getattr(param, "hidden", False):
                continue
            longs = tuple(
                o for o in (*param.opts, *param.secondary_opts) if o.startswith("--")
            )
            if longs:
                found.append((path, longs))

    walk(typer.main.get_command(app), "")
    return found


def _undocumented(options: Iterable[tuple[str, tuple[str, ...]]]) -> list[str]:
    sections = _sections(_read(REFERENCE))
    missing: list[str] = []
    for path, longs in options:
        top = re.compile(rf"yazses {re.escape(path.split()[0])}(?![\w-])")
        text = "\n".join(s for s in sections if top.search(s))
        if not any(re.search(rf"{re.escape(o)}(?![\w-])", text) for o in longs):
            missing.append(f"yazses {path} {' / '.join(longs)}")
    return missing


def test_every_shipped_option_is_in_the_cli_reference() -> None:
    options = _shipped_options()
    assert len(options) > 80, f"the walk found only {len(options)} options"
    missing = _undocumented(options)
    assert not missing, (
        "These options ship but no docs/cli-reference.md section about their command "
        "names them:\n" + "\n".join(missing)
    )


def test_the_option_check_notices_a_missing_one() -> None:
    assert _undocumented([("start", ("--zz-not-an-option",))])


# --- instructions a user can actually run -------------------------------------


def test_experimental_enable_instructions_carry_force() -> None:
    experimental = {
        f.slug for f in feature_status(Config()) if f.tier == EXPERIMENTAL and f.wired
    }
    assert "gaze" in experimental
    pages = [DOCS / "capability-matrix.md", DOCS / "store-submission.md"]
    for folder in ("how-to", "tutorials", "use-cases"):
        pages += sorted((DOCS / folder).rglob("*.md"))
    broken: list[str] = []
    for page in pages:
        for number, line in enumerate(_read(page).splitlines(), 1):
            for match in re.finditer(r"yazses features enable ([a-z][\w-]*)([^`\n]*)", line):
                if match[1] in experimental and "--force" not in match[2]:
                    broken.append(f"{page.relative_to(ROOT)}:{number}: {match[0].strip()}")
    assert not broken, (
        "These instructions are refused as written (experimental needs --force):\n"
        + "\n".join(broken)
    )


def test_the_multilingual_designed_count_matches_the_registry() -> None:
    members = [f for f in feature_status(Config()) if f.category == CAT_LANG]
    designed = sum(not f.wired for f in members)
    expected = f"({designed} of {len(members)} designed"
    assert expected in " ".join(_read(PUBLIC).split()), (
        f"docs/architecture.md should say {expected!r}"
    )
