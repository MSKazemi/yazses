"""A setting or flag named in a **shipped message** must exist, as in the docs.

Three families of advice are checked in this repository, and two of them were checked
in only one of the two places advice lives.

| what the advice names | in `docs/` | in a shipped string |
|---|---|---|
| a command | `test_advice_names_real_commands.py` | same file |
| a `--flag` | `test_docs_flags_exist.py` | **nothing — until this file** |
| a `[section] key` | `test_docs_config_keys_exist.py` | **nothing — until this file** |

The command guard covers both halves and its docstring says why the shipped half is the
one that matters more:

    an undocumented command is a gap, while advice naming a command that does not
    exist is a dead end handed to someone who is already stuck.

That reasoning is about *advice*, not about commands, and applies verbatim to a flag and
to a setting. A page is read while things are working; a runtime message is read when
they are not. `yazses doctor`, the mic-change notification, the settings window and the
"could not type that" toast all tell people what to set, and none of those strings was
compared against the config the daemon actually loads.

## Why this cannot drift from its two twins

The predicates are **imported**, not re-implemented: `_resolves` and `_INLINE` come from
the docs config guard, `_flag_table` and `INVOCATION` from the docs flag guard. If a
future change teaches one of them a new spelling, this file learns it in the same commit.
Re-writing them here is exactly the mistake that produced the asymmetry above.

## The corpus, measured

`[section] key` is matched **inside backticks**, the same convention the docs guard keys
on. Measured against the alternatives before choosing: backticked gives 101 mentions and
zero false positives; requiring `= value` gives 60 and matches the literal placeholder
`[section] key = value` in two docstrings; a bare `[section] word` gives 203 and reads
ordinary English as settings (`[endpoint] is`, `[personalize] on`), plus `pyproject.toml`'s
own `[project] authors`, which is a different file's schema entirely.

**The result today is zero in both directions**, which is the point of pinning it now.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.test_docs_config_keys_exist import _INLINE, _resolves
from tests.test_docs_flags_exist import INVOCATION, _flag_table

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "yazses"

#: Floors, not exact counts: a guard whose corpus can quietly empty passes on anything,
#: and this repository has shipped that failure more than once. Set below today's
#: measurements -- 101 backticked settings and 57 flagged invocations, out of 16406
#: shipped string literals -- so ordinary editing does not trip them while a collapse does.
_MIN_SETTINGS = 60
_MIN_FLAGS = 30


def _shipped_strings() -> list[tuple[Path, int, str]]:
    """Every string literal in the package — what a user can actually be shown.

    Deliberately not the `"yazses "`-filtered collector the command guard uses: a message
    that names a setting rarely names a command in the same breath, and filtering on one
    would silently shrink the corpus for the other.
    """
    out: list[tuple[Path, int, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — fails loudly elsewhere
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.append((path, node.lineno, node.value))
    return out


@pytest.fixture(scope="module")
def strings() -> list[tuple[Path, int, str]]:
    return _shipped_strings()


def _settings_in(text: str) -> list[tuple[str, str]]:
    return _INLINE.findall(text)


def _bad_settings(strings) -> list[str]:
    out = []
    for path, line, text in strings:
        for section, key in _settings_in(text):
            if not _resolves(section, key):
                out.append(f"{path.relative_to(ROOT)}:{line} — `[{section}] {key}`")
    return sorted(set(out))


def _bad_flags(strings) -> list[str]:
    table = _flag_table()
    root = table.get((), set())
    out = []
    for path, line, text in strings:
        for match in INVOCATION.finditer(text):
            tokens = match.group(1).split()
            path_key = next(
                (tuple(tokens[:n]) for n in (3, 2, 1) if tuple(tokens[:n]) in table), None
            )
            if path_key is None:
                continue  # not a command we ship; nothing to say about its flags
            for flag in re.findall(r"--[\w-]+", match.group(2)):
                if flag in table[path_key] or flag in root or flag == "--help":
                    continue
                out.append(
                    f"{path.relative_to(ROOT)}:{line} — `yazses {' '.join(path_key)} {flag}`"
                )
    return sorted(set(out))


def test_the_scan_sees_the_settings_shipped_in_messages(strings) -> None:
    found = [s for _, _, text in strings for s in _settings_in(text)]
    assert len(found) >= _MIN_SETTINGS, (
        f"only {len(found)} `[section] key` mentions found in shipped strings — "
        "a guard over an empty set passes on everything"
    )


def test_the_scan_sees_the_flags_shipped_in_messages(strings) -> None:
    table = _flag_table()
    found = [
        m
        for _, _, text in strings
        for m in INVOCATION.finditer(text)
        if any(tuple(m.group(1).split()[:n]) in table for n in (3, 2, 1))
    ]
    assert len(found) >= _MIN_FLAGS, (
        f"only {len(found)} flagged invocations found in shipped strings — "
        "this guard would be checking nothing"
    )


def test_no_shipped_message_names_a_setting_that_does_not_exist(strings) -> None:
    """`configcheck` drops an unknown key deliberately, so following such advice
    produces no error at all: the setting silently does nothing and the file loads."""
    bad = _bad_settings(strings)
    assert not bad, "shipped messages name settings that do not exist:\n" + "\n".join(bad)


def test_no_shipped_message_names_a_flag_the_command_does_not_have(strings) -> None:
    bad = _bad_flags(strings)
    assert not bad, "shipped messages name flags that do not exist:\n" + "\n".join(bad)


def test_the_guard_would_notice_an_invented_setting() -> None:
    planted = [(SRC / "planted.py", 1, "set `[audio] no_such_key` and restart")]
    assert _bad_settings(planted), "the setting scan cannot fail"
    assert not _bad_settings([(SRC / "planted.py", 1, "set `[audio] device` and restart")])


def test_the_guard_would_notice_an_invented_flag() -> None:
    planted = [(SRC / "planted.py", 1, "run `yazses doctor --no-such-flag` first")]
    assert _bad_flags(planted), "the flag scan cannot fail"
    assert not _bad_flags([(SRC / "planted.py", 1, "run `yazses doctor --mic` first")])
