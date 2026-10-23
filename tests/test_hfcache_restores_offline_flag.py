"""`cache_first()` must leave offline mode exactly as it found it.

The window sets `HF_HUB_OFFLINE=1` two ways -- the environment variable, and the
already-imported `huggingface_hub.constants.HF_HUB_OFFLINE` -- because either one
alone is a silent no-op. Restoring, though, only ever undid the second, using a
module reference captured *before* the window opened.

That reference is `None` in exactly the case `system/hfcache.py` exists to serve.
Its own docstring names it: the three loaders that need this are lazy optional
extras (`onnx_asr`, speechbrain, pyannote), so they import `huggingface_hub` for
the first time *inside* the window. The hub then initialises its constant from the
variable the window had just set, and the restore ran through the stale `None` --
so the constant stayed `True` for the remaining life of the process.

The observable failure was that Parakeet could never download its model on a
machine that did not already have it: the cache attempt missed correctly, and
`load_cache_first`'s retry -- the half that makes a first run work -- was itself
already offline, so it missed identically. `build_engine` then fell back to
faster-whisper with a logged exception, i.e. `features enable stt-parakeet`
appeared to succeed and silently kept decoding with Whisper.

faster-whisper hid this for the default engine, and that is why it went unnoticed:
it imports `huggingface_hub` at module scope, so for Whisper the constant is always
already present and the original restore path ran correctly.
"""
from __future__ import annotations

import sys
import types

import pytest

from yazses.system import hfcache

_CONSTANTS = "huggingface_hub.constants"


@pytest.fixture
def no_hub(monkeypatch):
    """Start from a process where `huggingface_hub.constants` is not imported."""
    monkeypatch.delitem(sys.modules, _CONSTANTS, raising=False)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)


def _import_hub_now(monkeypatch) -> types.ModuleType:
    """Mimic huggingface_hub being imported: it reads the env var *at import*.

    Installed through `monkeypatch`, never by assigning `sys.modules` directly. `no_hub`
    deletes the real module with `delitem(..., raising=False)`, which records nothing
    when the hub was never imported -- so a fake planted by assignment outlived the
    test, and a later `from huggingface_hub import constants` in the same worker got it
    (`test_hub_cache_dir_is_the_platform_default` failed under `-n auto`).
    """
    module = types.ModuleType(_CONSTANTS)
    module.HF_HUB_OFFLINE = hfcache._truthy(  # noqa: SLF001 - mirroring the library
        __import__("os").environ.get("HF_HUB_OFFLINE")
    )
    monkeypatch.setitem(sys.modules, _CONSTANTS, module)
    return module


def test_a_hub_imported_inside_the_window_is_restored_to_online(no_hub, monkeypatch):
    with hfcache.cache_first():
        constants = _import_hub_now(monkeypatch)
        assert constants.HF_HUB_OFFLINE is True, "the window must forbid hub requests"

    assert constants.HF_HUB_OFFLINE is False, (
        "the constant was left set, so every later hub request in this process -- "
        "including load_cache_first's own retry-online fallback -- is offline"
    )
    assert hfcache.offline_requested() is False


def test_a_user_who_asked_for_offline_still_has_it_afterwards(no_hub, monkeypatch):
    """A real opt-in must survive the window, whenever the hub happens to import."""
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    with hfcache.cache_first():
        constants = _import_hub_now(monkeypatch)

    assert constants.HF_HUB_OFFLINE is True
    assert hfcache.offline_requested() is True


def test_a_hub_already_imported_is_restored_to_its_prior_value(no_hub, monkeypatch):
    constants = _import_hub_now(monkeypatch)
    assert constants.HF_HUB_OFFLINE is False

    with hfcache.cache_first():
        assert constants.HF_HUB_OFFLINE is True

    assert constants.HF_HUB_OFFLINE is False


def test_a_cache_miss_still_downloads_when_the_hub_imports_inside_the_window(
    no_hub, monkeypatch
):
    """The end-to-end shape of the Parakeet failure, with no network involved.

    First call misses (the loader is offline and the model is not cached); the
    retry must run with the hub back online. Before the fix the second attempt saw
    `HF_HUB_OFFLINE` still true and failed the same way.
    """
    seen: list[bool] = []

    def load():
        constants = sys.modules.get(_CONSTANTS) or _import_hub_now(monkeypatch)
        offline = bool(constants.HF_HUB_OFFLINE)
        seen.append(offline)
        if offline:
            raise OSError("not in the local cache and outgoing traffic is disabled")
        return "model"

    assert hfcache.load_cache_first(load, what="the test model") == "model"
    assert seen == [True, False], (
        f"expected a cache-first attempt then an online retry, got offline={seen}"
    )



def test_the_fake_hub_does_not_outlive_its_test():
    """Teardown must remove the fake even when the real hub was never imported.

    That is the state of an xdist worker that reaches this file before anything has
    imported huggingface_hub, and the only state in which the old direct assignment
    leaked. Reproduce it, run one test's worth of patching, and undo it as pytest would.
    """
    real = sys.modules.pop(_CONSTANTS, None)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.delitem(sys.modules, _CONSTANTS, raising=False)  # what `no_hub` does
            fake = _import_hub_now(mp)
            assert sys.modules[_CONSTANTS] is fake
        assert _CONSTANTS not in sys.modules, (
            "the fake huggingface_hub.constants survived teardown; the next "
            "`from huggingface_hub import constants` in this worker would get it"
        )
    finally:
        if real is not None:
            sys.modules[_CONSTANTS] = real
