"""`yazses meeting notes` announced work it had already ruled out, then misdiagnosed it.

Run against a real stored meeting:

    $ yazses meeting notes 20260803-095635
    Generating minutes locally… (this can take a few minutes)
    Notes are off or no local model is set. Enable `[meeting] notes` and set
    `[meeting] notes_model` to a local GGUF.

Two faults in three lines.

## 1. The promise came before the check

`generate_minutes` returns `None` immediately when notes are off, so the "this can take a
few minutes" line was printed for work that was never going to start. The precondition
costs nothing to ask and is now asked first.

## 2. One message for five states, and for one of them it is wrong advice

`generate_minutes` returns `None` when: the transcript has no utterances, `[meeting] notes`
is off, `notes_model` is unset, llama-cpp-python is missing, the model path is not a file,
or every window failed to parse. All of them printed "notes are off or no local model is
set".

For an empty transcript that is simply false — no configuration produces minutes from no
utterances, and the message sends the user to change settings that were already correct.
That case is real here: an 11.6-second meeting on this machine finalized with a transcript
of `". . ."`, and once artefacts are cleaned it holds nothing at all.

"Off **or** no model" also asks the user to check two things the command can tell apart.

## Ordering is by what has to be fixed first

An empty transcript cannot be fixed by configuration at all. A missing dependency cannot be
fixed by a config key. A path that does not exist cannot be fixed by setting the path
again. So the checks run in that order, and the first one that fires is the one worth
acting on — the same "name the first broken link" rule `yazses verify` is built on.

## The probes are injected

`model_exists` and `have_llama` are parameters so this tests without a 4 GB GGUF or the
`notes` extra. `find_spec` is used rather than an import because importing `llama_cpp`
costs seconds and loads native code — far too much for a question asked before any work
begins.
"""

from __future__ import annotations

import pytest

from yazses.meeting.notes import notes_unavailable_reason


class _Cfg:
    def __init__(self, notes=True, notes_model="/models/m.gguf"):
        self.notes = notes
        self.notes_model = notes_model


def test_notes_off_says_so_and_nothing_else() -> None:
    reason = notes_unavailable_reason(_Cfg(notes=False))
    assert reason is not None
    assert "off" in reason
    assert "notes = true" in reason


def test_no_model_set_is_not_reported_as_notes_being_off() -> None:
    """The "or" that made the user check two things."""
    reason = notes_unavailable_reason(_Cfg(notes=True, notes_model=""))
    assert reason is not None
    assert "notes_model` is empty" in reason
    assert "are off" not in reason


def test_a_missing_dependency_names_the_extra() -> None:
    reason = notes_unavailable_reason(_Cfg(), have_llama=False)
    assert reason is not None
    assert "llama-cpp-python" in reason
    assert "--extra notes" in reason


def test_a_model_path_that_is_not_a_file_says_which_path() -> None:
    reason = notes_unavailable_reason(_Cfg(notes_model="/nope/m.gguf"),
                                      have_llama=True, model_exists=False)
    assert reason is not None
    assert "/nope/m.gguf" in reason


def test_everything_configured_returns_none() -> None:
    """A reason function that always finds a reason would block a working setup."""
    assert notes_unavailable_reason(_Cfg(), have_llama=True, model_exists=True) is None


def test_an_empty_transcript_is_not_blamed_on_configuration() -> None:
    """The wrong-advice case, and a real one on this machine."""
    reason = notes_unavailable_reason(_Cfg(), utterances=[], have_llama=True,
                                      model_exists=True)
    assert reason is not None
    assert "nothing to summarise" in reason
    assert "Nothing is wrong with your notes settings" in reason


def test_an_empty_transcript_outranks_every_config_fault() -> None:
    """Fixing config cannot help, so it must not be the thing suggested.

    A meeting recorded against a dead microphone hits this with notes never configured —
    the state where the old message was most misleading.
    """
    reason = notes_unavailable_reason(_Cfg(notes=False, notes_model=""), utterances=[])
    assert reason is not None
    assert "nothing to summarise" in reason
    assert "notes = true" not in reason


def test_utterances_none_means_not_asked_rather_than_empty() -> None:
    """The CLI passes them; another caller may not. `None` must not read as empty."""
    assert notes_unavailable_reason(_Cfg(notes=False), utterances=None) is not None
    assert "nothing to summarise" not in notes_unavailable_reason(
        _Cfg(notes=False), utterances=None
    )


def test_a_non_empty_transcript_falls_through_to_the_config_checks() -> None:
    reason = notes_unavailable_reason(_Cfg(notes=False), utterances=["something"])
    assert reason is not None
    assert "off" in reason


def test_the_cli_checks_before_it_announces() -> None:
    """The order is the fix; a reason function called after the echo changes nothing."""
    import inspect

    from yazses.cli import meeting_notes

    source = inspect.getsource(meeting_notes)
    # The CALL, not the name: `notes_unavailable_reason` also appears in the import block
    # at the top of the function, which is above the echo whichever order the body is in.
    # The first version of this assertion matched that import and could never fail —
    # caught by red-green, when reordering the body left it green.
    call = source.index("if (reason := notes_unavailable_reason")
    echo = source.index('typer.echo("Generating minutes')
    assert call < echo, (
        "the availability check must run before the 'this can take a few minutes' line"
    )


def test_the_post_check_failure_no_longer_blames_config() -> None:
    """Once the preconditions pass, `None` means the model produced nothing usable.

    Reporting that as "notes are off" sends the user to a setting that is already right.
    """
    import inspect

    from yazses.cli import meeting_notes

    source = inspect.getsource(meeting_notes)
    assert "Notes are off or no local model is set" not in source
    assert "no usable minutes" in source


def test_it_does_not_import_llama_cpp_to_answer() -> None:
    """Importing costs seconds and loads native code — too much for a precondition."""
    import ast
    import inspect

    from yazses.meeting import notes

    fn = ast.parse(inspect.getsource(notes.notes_unavailable_reason)).body[0]
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body
    code = "\n".join(ast.unparse(node) for node in body)
    assert "import llama_cpp" not in code
    assert "find_spec" in code


@pytest.mark.parametrize("missing", ["notes", "notes_model"])
def test_a_config_object_without_the_attribute_does_not_explode(missing: str) -> None:
    """An older config, or a duck-typed one from a test, must not raise here."""
    cfg = _Cfg()
    delattr(cfg, missing)
    assert notes_unavailable_reason(cfg) is not None
