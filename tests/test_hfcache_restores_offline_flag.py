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


def _import_hub_now() -> types.ModuleType:
    """Mimic huggingface_hub being imported: it reads the env var *at import*."""
    module = types.ModuleType(_CONSTANTS)
    module.HF_HUB_OFFLINE = hfcache._truthy(  # noqa: SLF001 - mirroring the library
        __import__("os").environ.get("HF_HUB_OFFLINE")
    )
    sys.modules[_CONSTANTS] = module
    return module


def test_a_hub_imported_inside_the_window_is_restored_to_online(no_hub):
    with hfcache.cache_first():
        constants = _import_hub_now()
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
        constants = _import_hub_now()

    assert constants.HF_HUB_OFFLINE is True
    assert hfcache.offline_requested() is True


def test_a_hub_already_imported_is_restored_to_its_prior_value(no_hub):
    constants = _import_hub_now()
    assert constants.HF_HUB_OFFLINE is False

    with hfcache.cache_first():
        assert constants.HF_HUB_OFFLINE is True

    assert constants.HF_HUB_OFFLINE is False


def test_a_cache_miss_still_downloads_when_the_hub_imports_inside_the_window(no_hub):
    """The end-to-end shape of the Parakeet failure, with no network involved.

    First call misses (the loader is offline and the model is not cached); the
    retry must run with the hub back online. Before the fix the second attempt saw
    `HF_HUB_OFFLINE` still true and failed the same way.
    """
    seen: list[bool] = []

    def load():
        constants = sys.modules.get(_CONSTANTS) or _import_hub_now()
        offline = bool(constants.HF_HUB_OFFLINE)
        seen.append(offline)
        if offline:
            raise OSError("not in the local cache and outgoing traffic is disabled")
        return "model"

    assert hfcache.load_cache_first(load, what="the test model") == "model"
    assert seen == [True, False], (
        f"expected a cache-first attempt then an online retry, got offline={seen}"
    )
