"""The catalog said "nothing runs until you say 'run it'". There is no 'run it'.

`yazses shellpipe` turns spoken stages into a shell pipeline. Its own docstring is
unambiguous — *"Prints the pipeline for you to review and run — it NEVER executes
anything."* The capability catalog said something else:

    Speak stages … → renders 'ls | grep error | wc -l' as text;
    nothing runs until you say 'run it'.

That sentence promises a spoken confirm-and-run flow. There is no "run it" grammar
anywhere in the product, `shellpipe` is a CLI command the daemon never sees, and the CLI
contains no subprocess call at all. The description is now what the code does.

## Why the wording mattered more than it looks

It reads as a *safety* claim — "nothing runs **until**" implies something eventually does,
under a confirmation. A user who believes there is a confirm step is a user who might speak
a pipeline expecting a gate to catch it. There is no gate because there is no execution,
which is safer, and saying so plainly is worth more than the implied one.

It is also the third instance of one shape in this sweep: `windowctl` advertised layout
verbs its backend cannot perform, `wordgoal` advertised spoken progress with no grammar
behind it, and this. A description written alongside a design outlives the part of the
design that shipped.

## `dryrun_wrap` is the other half of that missing path

`shellpipe/build.py::dryrun_wrap` turns `rm -rf build` into `rm -i -rf build`. Nothing in
`src/` calls it — it is exactly the helper a run path would need, written for one that was
never built.

It is kept, not deleted: making that decision in advance, when nobody is in a hurry, is the
valuable part. `tests/test_orphan_modules.py` tracks whole *modules*, and this module is
reachable through its two other functions, so a function-level orphan is invisible to it.
Pinned here instead, so wiring it is deliberate.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from yazses.config import Config
from yazses.shellpipe.build import dryrun_wrap, parse_stages, render_pipeline
from yazses.system.features import feature_status


def _shellpipe():
    return next(f for f in feature_status(Config()) if f.slug == "shellpipe")


def test_the_description_does_not_promise_a_run_step() -> None:
    feat = _shellpipe()
    text = f"{feat.why} {feat.example} {feat.use_case}".lower()
    assert "run it" not in text, (
        "the catalog promises a spoken 'run it' confirmation; no such grammar exists"
    )


def test_the_description_says_what_is_true() -> None:
    """Trimming the false claim to nothing would be the other way to be wrong."""
    assert "never executes" in _shellpipe().why.lower()


def test_the_command_contains_no_way_to_execute_anything() -> None:
    """The claim, asserted against the code rather than the prose.

    If a run path is added, this fails — at which point the description may promise one.
    """
    from yazses.cli import shellpipe

    tree = ast.parse(inspect.cleandoc(inspect.getsource(shellpipe)))
    called = {
        getattr(n.func, "attr", getattr(n.func, "id", ""))
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    for forbidden in ("run", "Popen", "call", "check_call", "check_output", "system"):
        assert forbidden not in called, (
            f"`yazses shellpipe` now calls {forbidden}() — it used to promise it never "
            f"executes anything, and the catalog wording depends on that"
        )


def test_rendering_still_works() -> None:
    """The feature itself is fine; only the sentence about it was wrong."""
    pipeline = render_pipeline(parse_stages("list files, filter for error, count lines"))
    assert "|" in pipeline
    assert pipeline.startswith("ls")


@pytest.mark.parametrize(
    "pipeline,expected",
    [("rm -rf build", "rm -i -rf build"), ("ls | wc -l", "ls | wc -l"), ("", "")],
)
def test_the_orphaned_dry_run_helper_still_works(pipeline: str, expected: str) -> None:
    """Kept rather than deleted, so it must keep working."""
    assert dryrun_wrap(pipeline) == expected


def test_the_dry_run_helper_is_still_unwired() -> None:
    """Fails the day someone wires it, which is when the note above must be removed.

    A module-level orphan ledger cannot see this: `shellpipe/build.py` is reachable
    through `parse_stages` and `render_pipeline`.
    """
    import subprocess

    hits = subprocess.run(
        ["git", "grep", "-l", "dryrun_wrap", "--", "src/"],
        capture_output=True, text=True, check=False,
    ).stdout.split()
    assert hits == ["src/yazses/shellpipe/build.py"], (
        f"dryrun_wrap is now referenced from {hits} — if the run path exists, drop the "
        f"'(orphan)' note in its docstring and this test"
    )
