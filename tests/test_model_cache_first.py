"""Loading a model that is already on disk must not depend on the network answering.

Measured on this project's laptop with a **fully cached** `base.en`: **1.9 s** with
`HF_HUB_OFFLINE=1`, and **still running after 180 s** without it, at 3 s of user CPU — so
blocked on I/O rather than working. A hub revalidation round-trip has no timeout, and a
network that neither answers nor refuses turns a local file into an unbounded hang.

`stt/faster_whisper.py` was fixed at its own call (`local_files_only=True`, pinned by
`test_stt_model_cache.py`). The three other loaders take no such argument, so
`system/hfcache.py` sets the switch one layer down, in `huggingface_hub` itself. These
tests pin the behaviour that fix has to have, and — because the same omission is what left
three loaders unguarded for as long as it did — that no *fourth* one can ship without it.

Nothing here imports speechbrain, onnx-asr or pyannote: they are optional extras that are
not installed in CI, which is exactly why the bug survived. The guard reads source.
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys

import pytest

from yazses.system.hfcache import cache_first, load_cache_first, offline_requested

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "yazses"

# --- the switch ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Neither variable set, whatever the developer's shell says."""
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)


def test_the_hub_is_forbidden_inside_the_context():
    with cache_first():
        assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert "HF_HUB_OFFLINE" not in os.environ


def test_an_unset_variable_is_left_unset_not_set_to_zero():
    """The hub distinguishes unset from `0`; leaving `0` behind is a silent change."""
    with cache_first():
        pass
    assert "HF_HUB_OFFLINE" not in os.environ


@pytest.mark.parametrize("prior", ["0", "1", "", "no"])
def test_whatever_was_there_before_is_restored_exactly(monkeypatch, prior):
    monkeypatch.setenv("HF_HUB_OFFLINE", prior)
    with cache_first():
        assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["HF_HUB_OFFLINE"] == prior


def test_the_switch_is_restored_even_when_the_load_raises():
    with pytest.raises(RuntimeError):
        with cache_first():
            raise RuntimeError("boom")
    assert "HF_HUB_OFFLINE" not in os.environ


def test_an_already_imported_hub_has_its_constant_flipped_too(monkeypatch):
    """The env var alone is a no-op for a package that imported the hub earlier.

    `huggingface_hub.constants.HF_HUB_OFFLINE` is read from the environment **at import
    time**, so a hub already in `sys.modules` would never see the variable. The
    enforcement point re-reads the constant per request, which is what makes flipping it
    work; if this stops being done, the guard silently protects nothing on exactly the
    machines where a model is most likely already loaded.
    """
    import types

    fake = types.ModuleType("huggingface_hub.constants")
    fake.HF_HUB_OFFLINE = False
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", fake)

    with cache_first():
        assert fake.HF_HUB_OFFLINE is True
    assert fake.HF_HUB_OFFLINE is False


def test_the_hub_is_read_from_sys_modules_and_never_imported():
    """Reaching for the flag must not drag the dependency into paths that never use it.

    Checked structurally rather than by observing `sys.modules`, because huggingface_hub
    is installed here and something else in the suite will already have imported it — an
    observational test would pass whatever this module did.
    """
    import yazses.system.hfcache as hfcache

    tree = ast.parse(pathlib.Path(hfcache.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "huggingface_hub" not in imported, (
        "importing huggingface_hub to set its own flag defeats the point -- the flag "
        "exists for loaders that may never have imported it"
    )


# --- the load ------------------------------------------------------------------


def test_a_cached_model_loads_in_one_attempt():
    calls = []
    result = load_cache_first(lambda: calls.append(dict(os.environ)) or "model",
                              what="a model")
    assert result == "model"
    assert len(calls) == 1, "a cached model must not be loaded twice"
    assert calls[0]["HF_HUB_OFFLINE"] == "1"


def test_a_missing_model_is_still_downloaded():
    """The half that keeps this from trading one failure mode for another."""
    seen = []

    def load():
        seen.append(os.environ.get("HF_HUB_OFFLINE"))
        if len(seen) == 1:
            raise FileNotFoundError("not cached")
        return "downloaded"

    assert load_cache_first(load, what="a model") == "downloaded"
    assert seen == ["1", None], "the retry must be allowed to reach the network"


def test_a_failure_on_the_download_is_raised_uncluttered():
    def load():
        raise ConnectionError("the network is down")

    with pytest.raises(ConnectionError) as excinfo:
        load_cache_first(load, what="a model")
    assert excinfo.value.__context__ is None, (
        "the online failure must not be chained to the cache miss -- the cause is the "
        "network, and 'During handling of the above' buries it"
    )


@pytest.mark.parametrize(
    "var,value",
    [("HF_HUB_OFFLINE", "1"), ("HF_HUB_OFFLINE", "yes"), ("TRANSFORMERS_OFFLINE", "1")],
)
def test_a_user_who_asked_for_offline_never_gets_a_download(monkeypatch, var, value):
    """Falling back would quietly defeat the setting whose purpose is to forbid one.

    `docs/how-to/air-gapped.md` tells people to verify a cached model with
    `HF_HUB_OFFLINE=1`; a fallback download makes that check answer the wrong question.
    """
    monkeypatch.setenv(var, value)
    calls = []

    def load():
        calls.append(1)
        raise FileNotFoundError("not cached")

    with pytest.raises(FileNotFoundError):
        load_cache_first(load, what="a model")
    assert len(calls) == 1, "no retry is permitted once offline was asked for"


def test_offline_requested_reads_the_in_process_flag_too(monkeypatch):
    import types

    fake = types.ModuleType("huggingface_hub.constants")
    fake.HF_HUB_OFFLINE = True
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", fake)
    assert offline_requested() is True


# --- the guard: no fourth loader may ship without this -------------------------

# Every hub-backed model entry point this project calls, and the module that owns the
# call. `faster-whisper` is absent on purpose: it takes `local_files_only=` directly and
# is pinned by `test_stt_model_cache.py`.
_LOADERS = {
    "src/yazses/voiceprint/ecapa.py": "from_hparams",
    "src/yazses/stt/parakeet.py": "load_model",
    "src/yazses/recimport/pyannote_backend.py": "from_pretrained",
}
# Attribute names that fetch a pretrained model through huggingface_hub.
_FETCHING_CALLS = {"from_hparams", "from_pretrained", "load_model", "snapshot_download"}
def _modules_calling_a_loader() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in SRC.rglob("*.py"):
        rel = str(path.relative_to(SRC.parent.parent))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _FETCHING_CALLS
        }
        if names:
            found[rel] = names
    return found


def test_every_hub_loader_in_the_tree_is_registered():
    """A new model loader fails this until it is listed — and listed means guarded.

    The inventory shape ADR-019 uses for outbound calls, for the same reason: three
    loaders went unguarded because nothing compared "modules that fetch a model" against
    "modules that load cache-first". Those two facts now sit in one test.
    """
    found = set(_modules_calling_a_loader())
    assert found == set(_LOADERS), (
        f"unregistered model loader(s): {sorted(found - set(_LOADERS))}; "
        f"registered but no longer loading: {sorted(set(_LOADERS) - found)}. "
        f"Route the call through `system/hfcache.load_cache_first` and add it here."
    )


@pytest.mark.parametrize("relpath", sorted(_LOADERS))
def test_each_loader_goes_through_the_cache_first_helper(relpath):
    text = (SRC.parent.parent / relpath).read_text(encoding="utf-8")
    assert "load_cache_first" in text, (
        f"{relpath} loads a pretrained model without trying the cache first, so a "
        f"blackholed network hangs it forever with the model already on disk."
    )


@pytest.mark.parametrize("relpath", sorted(_LOADERS))
def test_no_loader_call_escapes_the_helper(relpath):
    """Being in the file is not being on the call — the wrapper must enclose it.

    Two shapes count as enclosed, because both occur here and both are correct: the call
    inside a lambda argument (`load_cache_first(lambda: X.from_pretrained(...), ...)`),
    and the call inside a named function handed to the helper (`load_cache_first(_open,
    ...)`), which Parakeet needs — its int8-or-default decision must be *inside* the
    retried unit, or a checkpoint with no quantized weights triggers a download for
    weights that do not exist before falling back.
    """
    tree = ast.parse((SRC.parent.parent / relpath).read_text(encoding="utf-8"))
    wrapped: set[int] = set()
    handed_over: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "load_cache_first"
        ):
            wrapped.update(id(inner) for inner in ast.walk(node))
            handed_over.update(
                arg.id for arg in node.args if isinstance(arg, ast.Name)
            )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in handed_over
        ):
            wrapped.update(id(inner) for inner in ast.walk(node))
    loose = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _FETCHING_CALLS
        and id(node) not in wrapped
    ]
    assert not loose, (
        f"{relpath}: {len(loose)} pretrained-model call(s) at line(s) "
        f"{[n.lineno for n in loose]} are outside `load_cache_first(...)`."
    )
