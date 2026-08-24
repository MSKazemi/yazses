"""Every ``--help`` example that states a result must actually produce it.

An epilog line of the form ``yazses <cmd> ... -> <result>`` is a promise, and it is the
first thing a user copies. Nothing checked those promises, and two of them were wrong:
``shellpipe`` claimed ``grep 'python'`` where the real output is ``grep python``, and
``acronyms expand`` claimed "expands first use only" for an invocation that, on a machine
with no glossary, changed nothing and said nothing about why.

The claim itself selects the test: the examples are read out of the live Typer app rather
than from a list kept here, so a new ``->`` example is covered the day it is written, and
an example that cannot be executed as-is has to say why in ``_UNRUN`` instead of being
quietly skipped.
"""
from __future__ import annotations

import re
import shlex

import pytest
import typer.main
from typer.testing import CliRunner

from yazses.cli import app

# --------------------------------------------------------------------------------------
# Extraction: read the promises out of the app, never out of a list maintained here.
# --------------------------------------------------------------------------------------

_MARKUP = re.compile(r"\[/?[a-z ]+\]")

# A parenthetical set off by two or more spaces is an aside to the reader, not part of the
# claimed output: `-> ls | grep python | wc -l   (printed, never executed)`. One space is
# not enough to tell an aside from a real trailing token, so those stay part of the claim.
_ASIDE = re.compile(r"\s{2,}\([^()]*\)\s*$")


def _claimed(text: str) -> str:
    return _ASIDE.sub("", text).strip()


def _claims() -> list[tuple[str, str, str]]:
    """Return ``(command_path, invocation, claimed_result)`` for every ``->`` example.

    A claim is written either inline (``yazses braille "hi"   -> ...``) or on the line
    after the invocation, so both shapes are collected and attributed to the most recent
    ``yazses ...`` line.
    """
    root = typer.main.get_command(app)
    found: list[tuple[str, str, str]] = []

    def walk(cmd: object, path: str) -> None:
        lines = [_MARKUP.sub("", ln).strip() for ln in (getattr(cmd, "epilog", None) or "").splitlines()]
        invocation = ""
        for line in lines:
            if not line:
                continue
            if "yazses " in line and not line.startswith("->"):
                invocation, _, tail = line.partition("->")
                invocation = invocation.strip()
                if tail.strip():
                    found.append((path, invocation, _claimed(tail)))
            elif line.startswith("->"):
                found.append((path, invocation, _claimed(line[2:])))
        for name, sub in (getattr(cmd, "commands", None) or {}).items():
            walk(sub, f"{path} {name}")

    walk(root, "yazses")
    return found


# --------------------------------------------------------------------------------------
# Accounting: an example this suite does not execute must say why, here.
# --------------------------------------------------------------------------------------

_UNRUN: dict[str, str] = {
    "yazses gitvoice --run --yes":
        "the example's whole point is that it runs the git command for real; executing it "
        "in a test would push.",
}

# Claims phrased as a description of the output rather than the output itself. Each one is
# still executed -- only the comparison is relaxed to the substring named here, so the
# command is never left unrun.
_PROSE: dict[str, str] = {
    "CSV rows": "Ada,1815,London",
    "ALICE / dialogue": "ALICE",
    "Escape (one per line)": "Escape\nEscape",
}

# Setup an example needs before it can run at all, keyed by the invocation's prefix.
def _setup_bib(tmp_path) -> None:
    (tmp_path / "refs.bib").write_text(
        "@inproceedings{vaswani2017,\n"
        "  title = {Attention Is All You Need},\n"
        "  author = {Vaswani, Ashish and Shazeer, Noam},\n"
        "  year = {2017},\n"
        "  booktitle = {NeurIPS},\n"
        "}\n",
        encoding="utf-8",
    )


def _setup_glossary(tmp_path) -> None:
    import json

    (tmp_path / "acronyms.json").write_text(
        json.dumps({"API": "Application Programming Interface"}), encoding="utf-8"
    )


_SETUP = {
    "yazses cite": _setup_bib,
    "yazses acronyms expand": _setup_glossary,
}


def _unrun_reason(invocation: str) -> str | None:
    for key, reason in _UNRUN.items():
        if all(tok in invocation for tok in key.split()):
            return reason
    return None


# --------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------


def test_the_walker_actually_found_the_examples() -> None:
    """A guard that iterates is green on an empty collection; this pins that it is not."""
    claims = _claims()
    assert len(claims) >= 12, f"only {len(claims)} result-stating examples found"
    assert {c[0] for c in claims} >= {
        "yazses braille",
        "yazses case",
        "yazses chords",
        "yazses shellpipe",
        "yazses acronyms expand",
    }


def test_every_claim_is_either_executed_or_accounted_for() -> None:
    for path, invocation, claimed in _claims():
        if _unrun_reason(invocation):
            continue
        assert invocation.startswith("yazses ") or invocation.startswith("echo "), (
            f"{path}: cannot execute {invocation!r} and it is not listed in _UNRUN"
        )
        assert claimed, f"{path}: empty claim"


def _run(invocation: str, tmp_path, monkeypatch) -> str:
    """Execute one example line through the CLI and return what it printed."""
    stdin = ""
    if invocation.startswith("echo "):
        piped, _, invocation = invocation.partition("| ")
        stdin = shlex.split(piped.strip())[1] + "\n"
    argv = shlex.split(invocation)
    assert argv[0] == "yazses", invocation
    for prefix, setup in _SETUP.items():
        if invocation.startswith(prefix):
            setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("yazses.cli._acronyms_path", lambda: tmp_path / "acronyms.json")
    result = CliRunner().invoke(app, argv[1:], input=stdin)
    assert result.exit_code == 0, f"{invocation} exited {result.exit_code}:\n{result.output}"
    return result.output


@pytest.mark.parametrize(
    ("path", "invocation", "claimed"),
    [c for c in _claims() if not _unrun_reason(c[1])],
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_the_example_produces_what_it_claims(path, invocation, claimed, tmp_path, monkeypatch) -> None:
    expected = _PROSE.get(claimed, claimed)
    output = _run(invocation, tmp_path, monkeypatch)
    assert expected in output, (
        f"{path}: the help promises {claimed!r} but running\n  {invocation}\nprinted:\n{output}"
    )


def test_the_prose_map_never_covers_a_claim_that_already_matches() -> None:
    """A relaxed comparison that was not needed hides the strict one."""
    claimed_texts = {c[2] for c in _claims()}
    for prose in _PROSE:
        assert prose in claimed_texts, f"_PROSE holds {prose!r}, which no example claims"


def test_the_guard_bites_on_a_wrong_claim(tmp_path, monkeypatch) -> None:
    """The pre-fix state: shellpipe promised a quoted grep it does not emit."""
    output = _run('yazses shellpipe "list files then filter for python then count lines"', tmp_path, monkeypatch)
    assert "ls | grep python | wc -l" in output
    assert "grep 'python'" not in output, "the old claim would match, so the guard proves nothing"


def test_expand_says_why_it_expanded_nothing(tmp_path, monkeypatch) -> None:
    """The second defect: an empty glossary echoed the input back in silence."""
    monkeypatch.setattr("yazses.cli._acronyms_path", lambda: tmp_path / "absent.json")
    result = CliRunner().invoke(app, ["acronyms", "expand", "The API and the API"])
    assert result.exit_code == 0
    assert "The API and the API" in result.output
    assert "Glossary is empty" in result.output
    assert "yazses acronyms add" in result.output
