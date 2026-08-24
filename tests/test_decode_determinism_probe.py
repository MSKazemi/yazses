"""`probes/decode_determinism.py` — the leak that destroyed the first run of it.

The probe asks whether YazSes should decode greedily, and to answer that honestly it
rebuilds the engine for every repeat: "identical text" has to be a claim about the
*setting*, not about a warm model that happened not to drift. Rebuilding is therefore
deliberate and stays. What was not deliberate is that nothing released the model
afterwards.

`_patched` installs a closure on the engine that closes over the engine's own bound
`_decode_kwargs`, so the engine references itself. A self-referencing object is
unreachable by refcounting and can only be freed by the cycle collector, which runs when
it chooses. CTranslate2's weights are native memory freed by the model's destructor, so
until that collection happens the whole model stays resident. Fifteen `large-v3` builds
at roughly 4 GB each reached 64.8 GB on a 62 GB box with no swap and were OOM-killed at
run 19 of 20 — after three and a half hours, having written nothing.

Both halves of that are tested here: the cycle is real (so `_release` is not decoration),
and `_release` drops the model by **refcount alone**, with the cycle collector both
disabled and stubbed out, so the test cannot pass because something else cleaned up.
"""
from __future__ import annotations

import gc
import inspect
import weakref

import pytest

from tests.benchmark_deps import load


@pytest.fixture(scope="module")
def mod():
    return load("decode_determinism", "probes/decode_determinism.py")


class _Model:
    """Stands in for the native CTranslate2 model — the ~4 GB the leak was holding."""


class _FakeEngine:
    """Only the two attributes `_patched`/`_release` touch on `FasterWhisperEngine`."""

    def __init__(self) -> None:
        self._model = _Model()

    def _decode_kwargs(self, task=None) -> dict:
        return {"beam_size": 5}


@pytest.fixture
def no_gc():
    """Refcounting only: `gc.disable()` alone is not enough, `gc.collect()` still runs."""
    gc.disable()
    try:
        yield
    finally:
        gc.enable()
        gc.collect()


# --- 1. the defect is real -------------------------------------------------------------

def test_patching_the_engine_makes_it_reference_itself(mod, no_gc):
    engine = mod._patched(_FakeEngine(), {"temperature": 0.0})
    model_ref = weakref.ref(engine._model)
    del engine
    assert model_ref() is not None, (
        "the engine died on refcount alone, so there is no cycle and `_release` would "
        "be solving nothing — this control must fail before the fix below means anything"
    )


def test_the_patched_engine_still_applies_the_arm(mod):
    engine = mod._patched(_FakeEngine(), {"temperature": 0.0})
    kwargs = engine._decode_kwargs(None)
    assert kwargs["temperature"] == 0.0
    assert kwargs["beam_size"] == 5, "the arm must add to the engine's kwargs, not replace them"


# --- 2. the fix works, for the stated reason -------------------------------------------

def test_release_drops_the_model_by_refcount_alone(mod, no_gc, monkeypatch):
    monkeypatch.setattr(mod.gc, "collect", lambda *a, **k: 0)
    engine = mod._patched(_FakeEngine(), {"temperature": 0.0})
    model_ref = weakref.ref(engine._model)
    mod._release(engine)
    assert model_ref() is None, (
        "the native model outlived `_release` with the collector stubbed out, which is "
        "exactly the state that reached 64.8 GB and was OOM-killed"
    )


def test_release_breaks_the_cycle_rather_than_relying_on_a_collection(mod, no_gc, monkeypatch):
    monkeypatch.setattr(mod.gc, "collect", lambda *a, **k: 0)
    engine = mod._patched(_FakeEngine(), {"temperature": 0.0})
    engine_ref = weakref.ref(engine)
    mod._release(engine)
    del engine
    assert engine_ref() is None


def test_the_run_loop_actually_calls_it(mod):
    src = inspect.getsource(mod.run)
    assert "_release(engine)" in src, (
        "a release helper nothing calls is how the first run died with the helper "
        "already written"
    )


# --- 3. a partial result must survive a kill -------------------------------------------

def test_the_run_loop_checkpoints_after_every_arm(mod):
    assert "on_arm(out)" in inspect.getsource(mod.run)


def test_the_checkpoint_does_not_go_through_the_archive(mod):
    """`write_result` files any change under `results/history/` as a superseded run.

    Three checkpoints of one run would land there as two half-finished payloads dressed
    as measurements, which is the opposite of what the history exists to preserve.
    """
    src = inspect.getsource(mod.main)
    checkpoint = src[src.index("def checkpoint"):src.index("payload = run(")]
    assert "write_result" not in checkpoint
    assert "partial" in checkpoint


# --- 4. `summarise` is pure, and says what it means -------------------------------------

def _row(run: int, wer: float, sha: str, differs=()) -> dict:
    return {
        "run": run, "wer": wer, "hypothesis_sha256_16": sha,
        "insertions": 10, "substitutions": 5, "deletions": 1,
        "differs_from_run0": list(differs),
    }


def test_equal_wer_is_not_identical_text(mod):
    """Two runs can trade one insertion for another elsewhere and score the same."""
    out = mod.summarise([_row(0, 4.78, "aaaa"), _row(1, 4.78, "bbbb", ["1-2-3"])])
    assert out["identical_text"] is False
    assert out["distinct_outputs"] == 2
    assert out["wer_spread"] == 0.0, "the WER agrees; only the hash catches the difference"


def test_identical_text_needs_every_digest_to_agree(mod):
    out = mod.summarise([_row(r, 3.82, "same") for r in range(5)])
    assert out["identical_text"] is True
    assert out["distinct_outputs"] == 1
    assert out["n_utterances_ever_differing"] == 0


def test_the_four_arms_are_the_ones_the_docstring_names(mod):
    assert list(mod.ARMS) == ["baseline", "greedy", "greedy_no_context", "no_context"]
    assert mod.ARMS["baseline"] == {}, "the control must go through the same wrapper"
    assert mod.ARMS["greedy"] == {"temperature": 0.0}
    assert mod.ARMS["greedy_no_context"]["condition_on_previous_text"] is False


def test_the_two_factors_are_crossed(mod):
    """The arms must be a 2x2 over (fallback, conditioning), not three ad-hoc settings.

    Without `no_context` the design confounds them: `greedy_no_context` changes both
    knobs at once, so any difference it shows cannot be attributed to either. The fourth
    arm is what turns the comparison into something that can name a cause.
    """
    def cell(a):
        e = mod.ARMS[a]
        return (e.get("temperature") == 0.0, e.get("condition_on_previous_text") is False)

    assert {cell(a) for a in mod.ARMS} == {(False, False), (True, False),
                                          (True, True), (False, True)}


def test_an_arm_subset_is_filed_under_its_own_name(mod, tmp_path, monkeypatch):
    """A single-arm re-run must never overwrite the completed multi-arm measurement.

    `write_result` files a changed artifact's predecessor under `history/`, so reusing
    the name would retire the three-arm result and leave a one-arm payload standing as
    the current one -- the archive doing the opposite of what it exists for.
    """
    names = []
    monkeypatch.setattr(mod, "run", lambda *a, **k: {"arms": {}})
    monkeypatch.setattr(mod, "write_result", lambda name, payload: names.append(name) or "x")
    monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(mod.sys, "argv", ["p", "5", "test-other", "200", "large-v3", "no_context"])
    mod.main()
    assert names == ["probes/decode-determinism-large-v3-test-other-no_context"]


def test_the_full_run_keeps_the_unsuffixed_name(mod, tmp_path, monkeypatch):
    names = []
    monkeypatch.setattr(mod, "run", lambda *a, **k: {"arms": {}})
    monkeypatch.setattr(mod, "write_result", lambda name, payload: names.append(name) or "x")
    monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(mod.sys, "argv", ["p", "5", "test-other", "200", "large-v3"])
    mod.main()
    assert names == ["probes/decode-determinism-large-v3-test-other"]


def test_an_unknown_arm_is_refused_rather_than_silently_running_nothing(mod):
    """A typo must not decode zero utterances and write an empty artifact."""
    with pytest.raises(SystemExit, match="no such arm"):
        mod.run(1, "test-other", 1, "tiny.en", only=["greedy_no_ctx"])
