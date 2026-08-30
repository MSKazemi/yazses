"""The speech model has to arrive on the machine once — issue #310.

A personal firewall blocked that download and the daemon died with a raw
huggingface_hub traceback, rendered by the Windows bundle as "Failed to execute
script". These cover the two halves of the fix: the model can be fetched
deliberately, and when it cannot be fetched at all the user is told the three
ways to get it instead of being shown a stack trace.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.decoder_stack import needs_faster_whisper, needs_huggingface_hub
from yazses.stt import download
from yazses.stt.errors import (
    ModelUnavailableError,
    looks_like_a_blocked_network,
    model_unavailable_message,
)

# The exact error from the issue.
_WINERROR_10013 = (
    "Got: ConnectError: [WinError 10013] An attempt was made to access a socket "
    "in a way forbidden by its access permissions\nAn error happened while trying "
    "to locate the files on the Hub, and we cannot find the appropriate snapshot "
    "folder for the specified revision on the local disk. Please check your "
    "internet connection and try again."
)


# ---- the repo mapping --------------------------------------------------


@needs_faster_whisper
def test_mirror_matches_faster_whisper_exactly():
    """WHISPER_MODELS is a hand-mirrored copy of a private upstream dict. If
    upstream adds or repoints a model, the mirror sends users to a 404 — so the
    drift has to fail here rather than in someone's download."""
    from faster_whisper.utils import _MODELS

    assert download.WHISPER_MODELS == dict(_MODELS)


@pytest.mark.parametrize(
    ("name", "repo"),
    [
        ("base.en", "Systran/faster-whisper-base.en"),
        # The irregular ones -- a URL template would send these to a 404.
        ("large", "Systran/faster-whisper-large-v3"),
        ("turbo", "mobiuslabsgmbh/faster-whisper-large-v3-turbo"),
        ("distil-large-v3.5", "distil-whisper/distil-large-v3.5-ct2"),
    ],
)
def test_repo_id_is_looked_up_not_guessed(name, repo):
    assert download.whisper_repo_id(name) == repo
    assert download.whisper_model_url(name) == f"https://huggingface.co/{repo}"


def test_explicit_hub_id_passes_through():
    assert download.whisper_repo_id("someorg/some-ct2-model") == "someorg/some-ct2-model"


def test_local_path_has_no_remote(tmp_path):
    local = tmp_path / "my-model"
    local.mkdir()
    assert download.whisper_repo_id(str(local)) is None
    assert download.whisper_model_url(str(local)) is None


def test_is_whisper_model_only_accepts_short_names():
    assert download.is_whisper_model("small.en")
    assert not download.is_whisper_model("someorg/some-model")
    assert not download.is_whisper_model("")


# ---- the cache ---------------------------------------------------------


def _make_snapshot(cache: Path, repo: str) -> None:
    d = cache / ("models--" + repo.replace("/", "--")) / "snapshots"
    d.mkdir(parents=True)


def test_is_cached_finds_a_downloaded_model(tmp_path):
    _make_snapshot(tmp_path, "Systran/faster-whisper-base.en")
    assert download.is_cached("base.en", tmp_path)


def test_is_cached_is_false_for_a_missing_model(tmp_path):
    assert not download.is_cached("base.en", tmp_path)


def test_a_bare_directory_without_snapshots_is_not_cached(tmp_path):
    """An interrupted download leaves the directory but no snapshots — treating
    that as present would send the daemon back into the failure it just had."""
    (tmp_path / "models--Systran--faster-whisper-base.en").mkdir(parents=True)
    assert not download.is_cached("base.en", tmp_path)


def test_a_local_model_directory_counts_as_cached(tmp_path):
    local = tmp_path / "ct2-model"
    local.mkdir()
    assert download.is_cached(str(local), tmp_path)


def test_missing_cache_dir_is_not_an_error(tmp_path):
    assert not download.is_cached("base.en", tmp_path / "nope")


@needs_huggingface_hub
def test_hub_cache_dir_is_the_platform_default():
    """The docs claimed %LOCALAPPDATA%\\huggingface on Windows; huggingface_hub
    actually uses ~/.cache/huggingface/hub everywhere. Ask the library."""
    from huggingface_hub import constants

    assert download.hub_cache_dir() == Path(constants.HF_HUB_CACHE)


# ---- the message -------------------------------------------------------


def test_blocked_network_is_recognised():
    assert looks_like_a_blocked_network(_WINERROR_10013)


def test_an_unrelated_failure_is_not_called_a_network_problem():
    assert not looks_like_a_blocked_network(ValueError("corrupt weights file"))


def test_message_names_all_three_routes():
    msg = model_unavailable_message("base.en", _WINERROR_10013)
    assert "yazses model download base.en" in msg          # 1. do it deliberately
    assert "firewall" in msg.lower()                        # 2. unblock it
    assert "https://huggingface.co/Systran/faster-whisper-base.en" in msg  # 3. by hand
    assert str(download.hub_cache_dir()) in msg             # ...and where it goes


def test_message_carries_the_original_cause():
    """Losing the cause would make the report unactionable for anything that is
    not a firewall."""
    msg = model_unavailable_message("base.en", _WINERROR_10013)
    assert "WinError 10013" in msg


def test_message_adds_the_firewall_hint_only_when_it_fits():
    blocked = model_unavailable_message("base.en", _WINERROR_10013)
    other = model_unavailable_message("base.en", ValueError("disk full"))
    assert "blocked connection" in blocked
    assert "blocked connection" not in other
    # but the three routes are offered either way
    assert "yazses model download base.en" in other


def test_error_str_is_the_guidance():
    """`log.error("%s", exc)` has to print the advice, not a class name."""
    exc = ModelUnavailableError("base.en", _WINERROR_10013)
    assert "yazses model download base.en" in str(exc)
    assert exc.model == "base.en"


# ---- the load path -----------------------------------------------------


@needs_faster_whisper
def test_load_model_converts_a_failed_download(mocker):
    """The conversion point. _load_model tries the cache, then the network; a
    network failure has to leave as ModelUnavailableError or the daemon gets a
    huggingface_hub traceback it cannot explain."""
    from yazses.stt import faster_whisper as fw

    mocker.patch.object(
        fw, "WhisperModel", side_effect=OSError(_WINERROR_10013)
    )
    with pytest.raises(ModelUnavailableError) as caught:
        fw._load_model("base.en", "cpu", "int8")

    assert caught.value.model == "base.en"
    assert "yazses model download base.en" in str(caught.value)
    # the original is preserved for anyone debugging a non-firewall cause
    assert isinstance(caught.value.__cause__, OSError)


@needs_faster_whisper
def test_load_model_still_prefers_the_cache(mocker):
    """The cache-first behaviour must survive: a cached model loads with no
    second (network) call at all."""
    from yazses.stt import faster_whisper as fw

    sentinel = object()
    ctor = mocker.patch.object(fw, "WhisperModel", return_value=sentinel)

    assert fw._load_model("base.en", "cpu", "int8") is sentinel
    assert ctor.call_count == 1
    assert ctor.call_args.kwargs["local_files_only"] is True


@needs_faster_whisper
def test_load_model_falls_back_to_downloading(mocker):
    """A cache miss still downloads — the guard must not turn a first run into
    an error."""
    from yazses.stt import faster_whisper as fw

    sentinel = object()
    ctor = mocker.patch.object(
        fw, "WhisperModel", side_effect=[FileNotFoundError("not cached"), sentinel]
    )

    assert fw._load_model("base.en", "cpu", "int8") is sentinel
    assert ctor.call_count == 2
    assert "local_files_only" not in ctor.call_args.kwargs


def test_model_name_with_no_resolvable_url_still_gets_advice(tmp_path):
    """An unresolvable name must not drop the user off a cliff — routes 1 and 2
    still apply even when we cannot name a download URL."""
    msg = model_unavailable_message(str(tmp_path / "gone"), "boom")
    assert "yazses model download" in msg
    assert "firewall" in msg.lower()
