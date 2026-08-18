"""Speaker labels: why they are unavailable, and the ONE command that fixes it.

`diarization_status` has always distinguished *"the Python package is missing"* from
*"the model files are missing"*. Both callers computed that distinction and then threw
it away when they gave advice:

* `yazses meeting status` printed the cause correctly and recommended
  `yazses transcribe --download-models` **for both**. With the extra missing that
  downloads ~45 MB and changes nothing — the absent thing is an importable module —
  so the user pays for a download and gets the identical message back.
* the daemon's `meeting start` warning named both remedies unconditionally, which is
  better but still asks for a step that cannot be acted on yet.

Found by running `yazses meeting status` on a machine where the extra is genuinely
absent, and reading the sentence it produced.

The rule these tests hold to is **name the next action, not the whole path**: when the
extra is missing the models are irrelevant until it is installed, and mentioning a
second step is how the wrong one gets attempted first.
"""

from __future__ import annotations

import pytest

from yazses.recimport.factory import diarization_advice


def _status(**over):
    base = {
        "requested": True,
        "backend": "sherpa",
        "extra_installed": True,
        "models_present": True,
        "ready": True,
    }
    base.update(over)
    return base


# ---- silence when there is nothing to say ---------------------------------


def test_ready_says_nothing():
    assert diarization_advice(_status()) is None


def test_not_requested_says_nothing_even_when_nothing_is_installed():
    """`[meeting] diarize` off is a choice, not a fault.

    Warning about missing speaker models to someone who never asked for speaker
    labels is the false alarm `diarization_status`'s docstring already exists to
    avoid; the advice layer must not reintroduce it.
    """
    assert diarization_advice(
        _status(requested=False, extra_installed=False, models_present=False, ready=False)
    ) is None


def test_an_empty_status_is_silent_rather_than_alarming():
    """An older daemon sends no `diarization` key at all."""
    assert diarization_advice({}) is None


# ---- the defect: one remedy for two different causes ----------------------


def test_a_missing_extra_names_the_install_and_not_the_download():
    """The bug, stated as a test.

    `--download-models` fetches ~45 MB whether or not the extra is importable, so
    recommending it here costs the user a download and leaves speaker labels exactly
    as unavailable.
    """
    advice = diarization_advice(_status(extra_installed=False, models_present=False, ready=False))
    assert advice is not None
    assert "yazses features enable meeting" in advice
    assert "--download-models" not in advice, (
        "downloading models cannot fix a missing Python package"
    )


def test_a_missing_extra_still_says_the_models_come_later():
    """Naming the next action must not imply it is the last one."""
    advice = diarization_advice(_status(extra_installed=False, ready=False))
    assert "fetched after" in advice


def test_missing_models_with_the_extra_present_names_the_download():
    advice = diarization_advice(_status(models_present=False, ready=False))
    assert advice is not None
    assert "--download-models" in advice
    assert "features enable meeting" not in advice, (
        "the extra is already installed; recommending it again is noise"
    )


def test_the_two_causes_never_give_the_same_advice():
    """The whole point. They did, and that is what made the message useless."""
    no_extra = diarization_advice(_status(extra_installed=False, ready=False))
    no_models = diarization_advice(_status(models_present=False, ready=False))
    assert no_extra != no_models


def test_pyannote_does_not_promise_a_download_that_may_be_gated():
    """Its pipeline is a gated repo: "not cached" may mean the terms were never accepted.

    `diarization_status`'s docstring already refuses to predict success there. Advice
    that said "run this" would be that prediction wearing an imperative.
    """
    advice = diarization_advice(
        _status(backend="pyannote", models_present=False, ready=False)
    )
    assert "conditions" in advice
    assert "--download-models" not in advice, "that command fetches the sherpa models"


def test_a_backend_that_cannot_diarize_says_so_instead_of_offering_an_install():
    """`[meeting] diarize = true` with `backend = "none"` is a config fault.

    No install fixes it, so advice naming one would send someone to install something
    that changes nothing — the same failure in a different place.
    """
    advice = diarization_advice(
        _status(backend="none", extra_installed=False, models_present=False, ready=False)
    )
    assert "backend" in advice
    assert "features enable" not in advice


@pytest.mark.parametrize(
    "over",
    [
        {"extra_installed": False, "ready": False},
        {"models_present": False, "ready": False},
        {"backend": "pyannote", "models_present": False, "ready": False},
        {"backend": "none", "ready": False},
    ],
)
def test_every_unavailable_state_says_transcripts_will_not_be_attributed(over):
    """The consequence, in every branch — it is the reason anyone should care."""
    advice = diarization_advice(_status(**over))
    assert advice and ("attributed" in advice or "cannot produce" in advice)


# ---- both surfaces go through it ------------------------------------------


def test_the_daemon_and_the_cli_both_use_the_shared_advice():
    """Two surfaces phrasing one fault differently is what this replaced.

    Checked in the source because the daemon path needs a live meeting config and the
    CLI path needs a running daemon; what regresses is one of them growing its own
    copy again, and that is visible here.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    import ast

    # Two refinements, each from a false positive this very guard produced:
    #
    # 1. The marker is the *sentence the advice opens with*, not a phrase like "the
    #    diarization extra" — `cli.py` says that legitimately in the `--diarize`
    #    flag's help text.
    # 2. Only **string literals** are searched, not raw file text. The first version
    #    read the file and matched the explanatory *comment* next to the fix,
    #    reporting the code that removed the duplication as duplication.
    #
    # A guard that flags prose is one that gets deleted rather than obeyed.
    opener = "Speaker labels are on but"

    def literals(path):
        tree = ast.parse((root / path).read_text(encoding="utf-8"))
        return [
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]

    assert any(opener in s for s in literals("src/yazses/recimport/factory.py"))
    for rel in ("src/yazses/core/daemon.py", "src/yazses/cli.py"):
        assert "diarization_advice" in (root / rel).read_text(encoding="utf-8"), (
            f"{rel} no longer uses the shared advice"
        )
        copies = [s for s in literals(rel) if opener in s]
        assert not copies, f"{rel} has grown its own copy of the advice wording: {copies}"
