"""The three guards between a transcript and the injector must run in order.

`CLAUDE.md` states it as an invariant: *"Three guards sit between a finished transcript
and the injector, in this order, and the order is load-bearing… Both run **before**
`staged`, which would otherwise swallow the confirm utterance as ordinary text."*

    _cmdsafety_gate   ->   _checkdigit_gate   ->   _stage_or_commit

Half of that was enforced. `test_cmdsafety_daemon.py` reads the call sites out of
`_on_hold_end` and asserts `_cmdsafety_gate` precedes `_stage_or_commit`.
`test_checkdigit_guard.py` collects the same calls into a **set** — which proves the gate
is reached and deliberately discards the ordering the invariant is about. So
`_checkdigit_gate` could be moved after staging and every existing test would stay green.

The consequence of that move is not subtle. `checkdigit` holds a failing number using
`ConfirmGate.hold()` — the *same* held slot and the *same* confirm word as `cmdsafety`,
so the user learns one release phrase. If staging ran first it would take the confirm
utterance as ordinary text to buffer, and a held card number could never be released at
all: the guard would fire and then trap the user behind it.

## Why this reads the source

The order is a property of `_on_hold_end`'s control flow, and every branch in it is
gated on a different config flag. Driving it end to end would need three features enabled
at once plus a microphone, an injector and a focused window; the AST check states the
invariant directly and runs anywhere. It is the same technique the sibling tests already
use — this file only adds the comparison they leave out.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from yazses.core.daemon import Daemon

#: In the order they must appear.
CHAIN = ["_cmdsafety_gate", "_checkdigit_gate", "_stage_or_commit"]


def _call_order() -> list[str]:
    """The guard method calls in `_on_hold_end`, in source order."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(Daemon._on_hold_end)))
    return [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in set(CHAIN)
    ]


def test_all_three_guards_are_reached() -> None:
    """A guard nothing calls passes every test written about the guard itself."""
    calls = _call_order()
    missing = [name for name in CHAIN if name not in calls]
    assert not missing, f"never reached from _on_hold_end: {missing}"


@pytest.mark.parametrize(
    "earlier,later",
    [("_cmdsafety_gate", "_checkdigit_gate"),
     ("_cmdsafety_gate", "_stage_or_commit"),
     ("_checkdigit_gate", "_stage_or_commit")],
)
def test_the_chain_runs_in_the_documented_order(earlier: str, later: str) -> None:
    calls = _call_order()
    assert calls.index(earlier) < calls.index(later), (
        f"{earlier} must run before {later}. Staging buffers an utterance as ordinary "
        "text, so a guard placed after it never sees the spoken confirm — the held "
        "command or number could then never be released, and the guard would trap the "
        "user behind it rather than protect them."
    )


def test_both_guards_share_one_release_phrase() -> None:
    """Why the ordering matters for *both*, not just the safety gate.

    `checkdigit` reuses `ConfirmGate`, so the two guards compete for the same held slot
    and the same confirm word. That shared slot is the reason each must see the confirm
    utterance before staging can take it.
    """
    import inspect as _inspect

    from yazses.checkdigit import guard as checkdigit_guard

    source = _inspect.getsource(checkdigit_guard)
    assert "ConfirmGate" in source or "confirm" in source.lower(), (
        "checkdigit no longer shares the confirm mechanism — if it has its own release "
        "phrase now, revisit whether it still has to precede staging"
    )


def test_the_reader_finds_real_calls_not_an_empty_list() -> None:
    """A guard over an empty set passes on everything.

    The comparison above is `index() < index()`, which raises on a missing name rather
    than passing — but only if the extraction works at all. Pin that it does.
    """
    calls = _call_order()
    assert len(calls) >= len(CHAIN), f"only found {calls}"
    assert set(calls) == set(CHAIN)
