"""Loading a cached model must not touch the network.

`WhisperModel(name)` defaults to `local_files_only=False`, so faster-whisper asks
huggingface_hub to revalidate the snapshot **even when every file is already cached**.
That put a network call on the startup path of a program whose headline claim is that
it does not need one, and it had no timeout: measured on a machine with `base.en` fully
cached, `yazses transcribe` sat at "Loading STT model" for over fifteen minutes at ~0%
CPU, against 2.3 s for the identical command with `HF_HUB_OFFLINE=1`.

These pin both halves of the fix — the cache is tried first, and a model that is not
cached is still downloaded, because trading a hang for a broken first run would be no
improvement at all.
"""
from __future__ import annotations

import pytest

from yazses.stt import faster_whisper as fw


@pytest.fixture
def loads(monkeypatch):
    """Record the kwargs of every `WhisperModel(...)` construction."""
    seen: list[dict] = []

    class _FakeModel:
        def __init__(self, model_name, **kwargs) -> None:
            seen.append({"model_name": model_name, **kwargs})

    monkeypatch.setattr(fw, "WhisperModel", _FakeModel)
    return seen


def test_a_cached_model_is_loaded_without_contacting_the_hub(loads):
    fw._load_model("base.en", "cpu", "int8")
    assert len(loads) == 1, "a cached model must be loaded in one attempt"
    assert loads[0]["local_files_only"] is True
    assert loads[0]["model_name"] == "base.en"


def test_load_passes_through_device_and_compute_type(loads):
    fw._load_model("small.en", "cuda", "float16")
    assert loads[0]["device"] == "cuda"
    assert loads[0]["compute_type"] == "float16"


def test_a_missing_model_still_downloads(monkeypatch):
    """The fallback is the whole reason this is safe — first run must still work."""
    seen: list[dict] = []

    class _FakeModel:
        def __init__(self, model_name, **kwargs) -> None:
            seen.append(kwargs)
            if kwargs.get("local_files_only"):
                raise OSError("not in the local cache")

    monkeypatch.setattr(fw, "WhisperModel", _FakeModel)
    fw._load_model("base.en", "cpu", "int8")

    assert len(seen) == 2, "a cache miss must fall back to a downloading load"
    assert seen[0]["local_files_only"] is True
    assert not seen[1].get("local_files_only"), "the retry must be allowed to download"


def test_a_download_failure_is_not_swallowed(monkeypatch):
    """Only the cache probe is forgiving. A real failure must still reach the caller,
    rather than leaving the engine holding no model.

    Since #310 it arrives as ModelUnavailableError rather than the raw error:
    the caller is the daemon's startup path, and a bare OSError there became a
    traceback the user could not act on. The original is chained, so nothing is
    lost — assert both, because "wrapped" must never come to mean "hidden".
    """
    from yazses.stt.errors import ModelUnavailableError

    class _FakeModel:
        def __init__(self, model_name, **kwargs) -> None:
            raise OSError("no route to host")

    monkeypatch.setattr(fw, "WhisperModel", _FakeModel)
    with pytest.raises(ModelUnavailableError) as caught:
        fw._load_model("base.en", "cpu", "int8")

    assert isinstance(caught.value.__cause__, OSError)
    assert "no route to host" in str(caught.value.__cause__)
    assert "no route to host" in str(caught.value), "the cause must survive into the advice"
