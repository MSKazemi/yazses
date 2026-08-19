"""Verbatim mode discards formatting by *position*, so a new transform must come before it.

`[profiles.app]` can map an application to the `verbatim` tone, and the spoken commands
"dictate verbatim" / "resume formatting" toggle the same thing. The daemon implements it by
running every formatting transform and then throwing the result away:

    verbatim_literal = text          # the cleaned literal, before any transform
    ...                              # ITN, symbols, conversions, self-repair, ...
    if verbatim_active:
        text = verbatim_literal      # discard all of it

That is correct today, and it is correct **because of where the restore sits**. A transform
added *below* that line escapes the bypass entirely and silently: a user who asked for
verbatim in their editor gets their text rewritten anyway, and nothing fails.

The failure mode is invisible in the ordinary way — the feature is off by default, the
transform is probably off by default too, and the two only interact for a user who turned
both on. So this pins the ordering rather than waiting for that report.

Same technique, and same reason, as `test_guard_chain_order.py`: an invariant that is a
property of one function's control flow, where every branch is behind a different config
flag, is cheaper and more honest to assert against the source than to reach by wiring up a
dozen features and a microphone.
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap

import pytest

from yazses.core.daemon import Daemon

#: Every formatting transform the bypass is meant to cover, by the name the daemon
#: imports. Derived from the source once and pinned here, so adding a transform without
#: adding it to this list is itself caught by `test_the_list_is_still_complete`.
TRANSFORMS = [
    "apply_conversions",
    "apply_self_repair",
    "apply_symbols",
    "balance_delimiters",
    "correct_text",
    "evaluate",
    "fix_articles",
    "normalize_entities",
    "restore_diacritics",
    "semantic_breaks",
]


def _source() -> str:
    return textwrap.dedent(inspect.getsource(Daemon._on_hold_end))


def _restore_line(source: str) -> int:
    for i, line in enumerate(source.splitlines()):
        if "text = verbatim_literal" in line:
            return i
    pytest.fail("the verbatim restore is gone — does verbatim still bypass anything?")


def _first_use(source: str, name: str) -> int | None:
    for i, line in enumerate(source.splitlines()):
        if re.search(rf"\b{re.escape(name)}\b", line):
            return i
    return None


def test_the_restore_exists_and_uses_the_pre_transform_text() -> None:
    """The premise: something is captured before the transforms and restored after."""
    source = _source()
    assert "verbatim_literal = text" in source
    assert "text = verbatim_literal" in source
    assert _first_use(source, "verbatim_literal") < _restore_line(source)


@pytest.mark.parametrize("transform", TRANSFORMS)
def test_every_transform_runs_before_the_bypass(transform: str) -> None:
    source = _source()
    used = _first_use(source, transform)
    if used is None:
        pytest.skip(f"{transform} is no longer called from _on_hold_end")
    assert used < _restore_line(source), (
        f"{transform} runs AFTER the verbatim restore, so verbatim mode no longer "
        "bypasses it — a user who asked for literal capture gets their text rewritten"
    )


def test_the_list_is_still_complete() -> None:
    """A new transform must be added here, or this guard quietly stops covering it.

    Reads the imports out of the region the bypass covers, so the list cannot drift
    behind the code without failing.
    """
    source = _source()
    start = _first_use(source, "verbatim_literal")
    end = _restore_line(source)
    region = "\n".join(source.splitlines()[start:end])
    imported = set(re.findall(r"from yazses\.[\w.]+ import ([\w]+)", region))

    # Helpers rather than transforms: they load data or classify, they do not rewrite.
    helpers = {"load_vocab", "vocab_path", "detect_scheme", "parse_structure", "redact",
               "resolve_temporal", "scan_confusables"}
    missing = sorted(imported - helpers - set(TRANSFORMS))
    assert not missing, (
        f"these are imported inside the verbatim-covered region but are not in "
        f"TRANSFORMS: {missing}. Add them, or add them to `helpers` if they do not "
        "rewrite the text."
    )


def test_the_restore_is_inside_the_dictation_branch() -> None:
    """`verbatim_literal` is only bound for dictation; using it elsewhere would raise."""
    tree = ast.parse(_source())
    names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "verbatim_literal"
    }
    assert names, "verbatim_literal vanished"
    # Both the binding and the use must sit under the same `if is_dictation:` block; the
    # cheap proxy is that neither appears before it.
    source = _source()
    assert _first_use(source, "is_dictation") < _first_use(source, "verbatim_literal")
