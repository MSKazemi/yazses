"""A message that names a config key must also name the command that writes it.

`yazses recall` on a fresh install answers:

    Recall unavailable: recall disabled -- set [recall] enabled = true

`recall` is a registered, wired capability, and this project's documented way to turn
one on is `yazses features enable <slug>` -- which writes the config comment-preservingly,
installs the feature's optional dependencies, sets **every** key the feature needs, and
then tells the user to restart. Hand-editing one key does none of that.

The sharpest case is `[tts]`: it is written by `yazses features enable read-back`, a slug
no one could derive from the section name, and that feature needs a **second** key
(`[accessibility] read_back`, default `"off"`) which the message never mentions. A user
who follows `set [tts] enabled = true` exactly still gets no read-back loop.

`cli.py` already had the right pattern in one place -- *"Requires `[meeting] enabled =
true` (`yazses features enable meeting`)"* -- and nothing made the other seventeen match
it. The section -> slug map here is read out of the feature registry's own `on_writes`,
never restated, so a new capability is covered the day it is registered.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from yazses.config import Config
from yazses.system.features import grouped_features

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "yazses"

#: `[section] enabled = true` in prose, however it is quoted or spaced.
MENTION = re.compile(r"\[([a-z_]+)\]\s*enabled\s*=\s*true")


def section_to_slugs() -> dict[str, set[str]]:
    """Which `features enable <slug>` writes `[section] enabled = true`.

    Derived from the registry, so it cannot fall behind it.
    """
    out: dict[str, set[str]] = {}
    for _cat, _blurb, feats in grouped_features(Config()):
        for feat in feats:
            for section, key, value, *_rest in feat.on_writes or ():
                if key == "enabled" and str(value).lower() == "true":
                    out.setdefault(section, set()).add(feat.slug)
    return out


def _names_the_command(text: str, slugs: set[str]) -> bool:
    return any(re.search(rf"features\s+enable\s+{re.escape(s)}\b", text) for s in slugs)


# --- the guard must be able to see anything at all ----------------------------------


def test_the_registry_yields_toggleable_sections() -> None:
    mapping = section_to_slugs()
    assert len(mapping) >= 20, f"registry yielded only {len(mapping)} sections"
    assert "recall" in mapping and "recall" in mapping["recall"]
    # The case no one could guess: the section and the slug share no name.
    assert mapping.get("tts") == {"read-back"}


def test_the_mention_pattern_matches_the_shapes_actually_used() -> None:
    for text in (
        "set [recall] enabled = true",
        "Requires `[meeting] enabled = true`",
        "``[macros] enabled = true``",
        "[punch_in] enabled  =  true",
    ):
        assert MENTION.search(text), text
    assert not MENTION.search("[recall] enabled = false")
    assert not MENTION.search("recall is enabled")


# --- surface 1: what `--help` prints ------------------------------------------------


def _help_texts() -> list[tuple[str, str]]:
    """Every command's help text, walked out of the Typer app itself.

    Groups are found by asking for a `commands` mapping, **not** by
    `isinstance(cmd, click.Group)`: `typer.core.TyperGroup` does not inherit from it
    (its MRO runs through `typer._click.core.Command`), so the isinstance form walks the
    root and stops -- one command instead of fifty-nine, and a guard that is silently
    blind. `test_the_help_walk_finds_the_whole_cli` is what makes that fail loudly.
    """
    import typer.main

    from yazses.cli import app

    command = typer.main.get_command(app)
    found: list[tuple[str, str]] = []

    def walk(cmd: object, path: str) -> None:
        text = f"{getattr(cmd, 'help', '') or ''}\n{getattr(cmd, 'short_help', '') or ''}"
        found.append((path, text))
        for name, sub in (getattr(cmd, "commands", None) or {}).items():
            walk(sub, f"{path} {name}")

    walk(command, "yazses")
    return found


def test_the_help_walk_finds_the_whole_cli() -> None:
    texts = _help_texts()
    assert len(texts) >= 50, f"only {len(texts)} commands walked"
    assert any(p == "yazses recall" for p, _ in texts)
    assert any(p == "yazses meeting start" for p, _ in texts)


def test_no_help_text_names_a_config_key_without_its_command() -> None:
    mapping = section_to_slugs()
    offences = []
    for path, text in _help_texts():
        for section in {m.group(1) for m in MENTION.finditer(text)}:
            slugs = mapping.get(section)
            if slugs and not _names_the_command(text, slugs):
                offences.append(f"`{path} --help` says [{section}] enabled = true but never "
                                f"names `yazses features enable {'/'.join(sorted(slugs))}`")
    assert not offences, "\n".join(offences)


# --- surface 2: what the daemon and CLI print at runtime ----------------------------


def _runtime_messages() -> list[tuple[str, int, str]]:
    """String literals a user can actually be shown.

    Two shapes, both read out of the syntax tree rather than listed: an argument to
    `typer.echo(...)`, and the value under a `"reason"` key in a returned dict (the IPC
    refusal that `yazses recall`/`say`/`tune` print verbatim).
    """
    out: list[tuple[str, int, str]] = []

    def literal(node: ast.AST) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return "".join(v.value for v in node.values
                           if isinstance(v, ast.Constant) and isinstance(v.value, str))
        if isinstance(node, ast.BinOp):
            return literal(node.left) + literal(node.right)
        return ""

    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(SRC.parent.parent).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name == "echo":
                    for arg in node.args:
                        if text := literal(arg):
                            out.append((rel, node.lineno, text))
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "reason":
                        if text := literal(value):
                            out.append((rel, node.lineno, text))
    return out


def test_the_runtime_scan_finds_messages() -> None:
    msgs = _runtime_messages()
    assert len(msgs) >= 200, f"only {len(msgs)} runtime messages found -- scan is broken"
    assert any("reason" not in t and "disabled" in t for _f, _n, t in msgs)


def test_the_runtime_scan_sees_the_message_this_guard_was_written_for() -> None:
    # `yazses recall` prints this verbatim; if the scan cannot see it, the guard is blind.
    assert any("recall disabled" in t for _f, _n, t in _runtime_messages())


def test_no_runtime_message_names_a_config_key_without_its_command() -> None:
    mapping = section_to_slugs()
    offences = []
    for file, line, text in _runtime_messages():
        for section in {m.group(1) for m in MENTION.finditer(text)}:
            slugs = mapping.get(section)
            if slugs and not _names_the_command(text, slugs):
                offences.append(f"{file}:{line} says [{section}] enabled = true but never "
                                f"names `yazses features enable {'/'.join(sorted(slugs))}`: "
                                f"{text.strip()[:80]!r}")
    assert not offences, "\n".join(offences)


@pytest.mark.parametrize(
    "text,ok",
    [
        ("set [recall] enabled = true", False),
        ("set [recall] enabled = true (`yazses features enable recall`)", True),
        ("set [tts] enabled = true (`yazses features enable read-back`)", True),
        ("set [tts] enabled = true (`yazses features enable tts`)", False),
    ],
)
def test_the_offence_rule_accepts_the_right_slug_and_only_that_slug(text: str, ok: bool) -> None:
    mapping = section_to_slugs()
    section = MENTION.search(text).group(1)  # type: ignore[union-attr]
    assert _names_the_command(text, mapping[section]) is ok
