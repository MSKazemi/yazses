"""Fetch the speech-to-text model deliberately, and say where it lands.

YazSes transcribes entirely offline, but the Whisper checkpoint still has to
reach the machine once. Until now that happened implicitly, inside
``WhisperModel(...)`` on the daemon's startup path — which is fine on an open
network and a crash on a locked-down one (issue #310: a personal firewall
blocked the socket and the daemon died with a raw traceback before it could say
what it wanted or why).

This module makes that step nameable:

* :func:`download_stt_model` — fetch it on purpose, with progress, from the CLI.
* :func:`whisper_model_url` — where it comes from, so a user on an air-gapped or
  firewalled box can fetch it by hand.
* :func:`hub_cache_dir` — where to put it if they do.

Nothing here downloads at import time, and the lookup helpers never import
``faster_whisper``: they have to work on the error path, where the whole problem
may be that the heavy runtime could not get what it needed.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "WHISPER_MODELS",
    "whisper_repo_id",
    "whisper_model_url",
    "is_whisper_model",
    "is_english_only",
    "language_model_problem",
    "hub_cache_dir",
    "download_stt_model",
]

# Short name → Hugging Face repo, mirroring ``faster_whisper.utils._MODELS``.
#
# Mirrored rather than imported for two reasons: this must be usable without
# loading CTranslate2, and it is a private name upstream. The mapping is NOT
# derivable from a template — `large` resolves to large-v3, the distil models
# use a different prefix, and `turbo` comes from another org entirely — so
# guessing the URL would send a user to a 404. `tests/test_stt_download.py`
# asserts this stays identical to upstream's, so drift fails the suite rather
# than the user's download.
WHISPER_MODELS: dict[str, str] = {
    "base": "Systran/faster-whisper-base",
    "base.en": "Systran/faster-whisper-base.en",
    "distil-large-v2": "Systran/faster-distil-whisper-large-v2",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "distil-large-v3.5": "distil-whisper/distil-large-v3.5-ct2",
    "distil-medium.en": "Systran/faster-distil-whisper-medium.en",
    "distil-small.en": "Systran/faster-distil-whisper-small.en",
    "large": "Systran/faster-whisper-large-v3",
    "large-v1": "Systran/faster-whisper-large-v1",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "medium": "Systran/faster-whisper-medium",
    "medium.en": "Systran/faster-whisper-medium.en",
    "small": "Systran/faster-whisper-small",
    "small.en": "Systran/faster-whisper-small.en",
    "tiny": "Systran/faster-whisper-tiny",
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}

_HUB = "https://huggingface.co"


def is_whisper_model(name: str) -> bool:
    """True for a name faster-whisper resolves itself (``base.en``, ``small``…).

    A hub id (``org/repo``) or a filesystem path is a valid model too, but it is
    not a *short name*, so it answers False — the caller already knows where
    those come from.
    """
    return (name or "").strip() in WHISPER_MODELS


def is_english_only(name: str) -> bool:
    """True for an ``.en`` checkpoint, which carries no language tokens at all.

    Not a preference — such a model *physically cannot* decode another language.
    Whisper transliterates rather than failing, so the user gets fluent-looking
    nonsense instead of an error, which is why every surface that lets someone
    choose a language has to check this before the choice reaches the daemon.
    """
    return (name or "").strip().lower().endswith(".en")


def language_model_problem(model: str, language: str) -> str | None:
    """Why *language* cannot work with *model*, or None if the pair is fine.

    One implementation, deliberately: this rule started as an inline condition on
    the daemon's startup path, where it could only ever be a log line nobody was
    watching. The settings window needs the same answer *before* writing, and a
    second copy of the condition is how the two drift.

    An empty language means auto-detect, which is valid on a multilingual model
    and merely redundant on an English-only one — not a problem either way.
    """
    lang = (language or "").strip()
    if not lang or lang.lower() == "en":
        return None
    if not is_english_only(model):
        return None
    suggestion = model.strip()[: -len(".en")] or "small"
    return (
        f"{lang!r} needs a multilingual model, but {model!r} is English-only — "
        f"speech would be mis-transcribed as English rather than refused. "
        f"Choose {suggestion!r} instead — drop the .en suffix."
    )


def whisper_repo_id(name: str) -> str | None:
    """The Hugging Face repo backing *name*, or None if it can't be resolved.

    Accepts a short name or a hub id; returns None for a local path, which has
    no remote to point at.
    """
    name = (name or "").strip()
    if not name:
        return None
    if name in WHISPER_MODELS:
        return WHISPER_MODELS[name]
    # An explicit hub id passes through: exactly one "/", no path separators.
    if name.count("/") == 1 and "\\" not in name and not Path(name).exists():
        return name
    return None


def whisper_model_url(name: str) -> str | None:
    """Browser URL for *name*, for someone fetching it by hand."""
    repo = whisper_repo_id(name)
    return f"{_HUB}/{repo}" if repo else None


def hub_cache_dir() -> Path:
    """Where huggingface_hub keeps downloaded snapshots.

    Asks huggingface_hub when it is importable, so ``HF_HOME``,
    ``HF_HUB_CACHE`` and ``XDG_CACHE_HOME`` are all honoured rather than
    re-derived (and re-derived wrongly — the docs claimed
    ``%LOCALAPPDATA%\\huggingface`` on Windows, but the default is
    ``~/.cache/huggingface/hub`` on every platform).
    """
    try:
        from huggingface_hub import constants

        return Path(constants.HF_HUB_CACHE)
    except Exception:  # noqa: BLE001 — fall back to the documented default
        base = os.environ.get("HF_HOME") or os.path.join(
            os.environ.get("XDG_CACHE_HOME") or os.path.join(Path.home(), ".cache"),
            "huggingface",
        )
        return Path(base) / "hub"


def is_cached(name: str, cache_dir: Path | None = None) -> bool:
    """True when *name* is already on disk and needs no network.

    Matches on the hub cache's ``models--org--repo`` directory name rather than
    importing faster_whisper, so `doctor` and `model list` stay fast and work
    even when the heavy runtime is unavailable. A local path is checked directly.
    """
    name = (name or "").strip()
    if not name:
        return False
    local = Path(name).expanduser()
    if local.exists():
        return True
    cache = hub_cache_dir() if cache_dir is None else cache_dir
    if not cache.exists():
        return False
    # Prefer the exact repo when we can resolve it; fall back to the trailing
    # segment so an unknown-but-valid hub id still reports honestly.
    repo = whisper_repo_id(name)
    exact = "models--" + repo.replace("/", "--") if repo else None
    token = name.split("/")[-1]
    for entry in cache.iterdir():
        if not (entry / "snapshots").exists():
            continue
        if exact is not None and entry.name == exact:
            return True
        if entry.name.startswith("models--") and entry.name.endswith(token):
            return True
    return False


def download_stt_model(name: str, *, echo=print) -> Path:
    """Download the Whisper checkpoint *name* and return its local directory.

    A no-op beyond a cache check when it is already present. Raises whatever
    huggingface_hub raises on a network failure — the caller decides how to
    present that, since the CLI and the daemon want very different wording.
    """
    from faster_whisper.utils import download_model

    repo = whisper_repo_id(name) or name
    echo(f"Downloading STT model {name!r} from {_HUB}/{repo} ...")
    path = Path(download_model(name))
    echo(f"Done: {path}")
    return path
