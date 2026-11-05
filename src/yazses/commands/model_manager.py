"""Registry and download utility for SLM intent-routing models (v0.4.1).

Models are GGUF files stored in the user's cache directory:
  Linux:   ~/.cache/yazses/models/
  macOS:   ~/Library/Caches/yazses/models/
  Windows: %LOCALAPPDATA%\\yazses\\models\\

Usage:
    from yazses.commands.model_manager import download_model, list_models
    path = download_model("qwen2.5-0.5b")
"""
from __future__ import annotations

import hashlib
import logging
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import platformdirs

log = logging.getLogger(__name__)

_CACHE_BASE = Path(platformdirs.user_cache_dir("yazses")) / "models"

#: Seconds allowed for the connection and for each socket read. Without one a stalled
#: server hangs ``yazses`` forever.
TIMEOUT_S = 30.0

#: A cached file smaller than this share of the registry's ``size_mb`` is a cut-off
#: transfer or an error page, never the model.
MIN_SIZE_FRACTION = 0.5

_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class ModelInfo:
    id: str
    filename: str
    url: str
    size_mb: int
    description: str
    #: Optional lowercase hex SHA-256 of the file. When set, a download must match it.
    sha256: str | None = None


REGISTRY: dict[str, ModelInfo] = {
    "qwen2.5-0.5b": ModelInfo(
        id="qwen2.5-0.5b",
        filename="qwen2.5-0.5b-instruct-q4_k_m.gguf",
        url=(
            "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF"
            "/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        ),
        size_mb=397,
        description="Qwen2.5 0.5B — fast intent classifier, recommended for Tier 2 routing",
    ),
    "phi3-mini": ModelInfo(
        id="phi3-mini",
        filename="Phi-3-mini-4k-instruct-q4.gguf",
        url=(
            "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf"
            "/resolve/main/Phi-3-mini-4k-instruct-q4.gguf"
        ),
        size_mb=2200,
        description="Phi-3 mini — higher accuracy, ~300 ms per query",
    ),
}


def models_dir() -> Path:
    _CACHE_BASE.mkdir(parents=True, exist_ok=True)
    return _CACHE_BASE


def list_models() -> list[ModelInfo]:
    return list(REGISTRY.values())


def local_path(model_id: str) -> Path | None:
    """Return the local path if the model is already downloaded, else None."""
    info = REGISTRY.get(model_id)
    if info is None:
        return None
    p = models_dir() / info.filename
    return p if _is_plausible(p, info) else None


def _min_bytes(info: ModelInfo) -> int:
    return int(info.size_mb * 1024 * 1024 * MIN_SIZE_FRACTION)


def _is_plausible(path: Path, info: ModelInfo) -> bool:
    """True when *path* exists and is not obviously truncated."""
    try:
        return path.is_file() and path.stat().st_size >= _min_bytes(info)
    except OSError:
        return False


def download_model(
    model_id: str,
    *,
    show_progress: bool = True,
    _opener: Callable[..., Any] | None = None,
) -> Path:
    """Download *model_id* to the local cache and return the path.

    Skips the download if a plausibly complete file already exists. Raises
    ValueError for unknown model IDs and re-raises network errors. The bytes go
    to ``<name>.part`` and are renamed into place only after the length (and the
    SHA-256, when the registry has one) checks out; on any failure the ``.part``
    file is removed and no final file exists.
    """
    info = REGISTRY.get(model_id)
    if info is None:
        known = ", ".join(REGISTRY)
        raise ValueError(f"Unknown model {model_id!r}. Known models: {known}")

    dest = models_dir() / info.filename
    if _is_plausible(dest, info):
        log.info("Model %s already present at %s", model_id, dest)
        return dest
    if dest.exists():
        log.warning("Ignoring truncated cached model %s; downloading again", dest)
        dest.unlink(missing_ok=True)

    log.info("Downloading %s (%d MB) from %s", model_id, info.size_mb, info.url)
    if show_progress:
        print(f"Downloading {info.id} ({info.size_mb} MB)…")

    opener = _opener or urllib.request.urlopen
    part = dest.with_name(dest.name + ".part")
    try:
        digest = hashlib.sha256()
        got = 0
        with opener(info.url, timeout=TIMEOUT_S) as resp, open(part, "wb") as out:
            raw_len = resp.headers.get("Content-Length") if resp.headers else None
            total = int(raw_len) if raw_len and raw_len.isdigit() else 0
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                got += len(chunk)
                if show_progress and total > 0:
                    pct = 100 * min(got, total) // total
                    bar = "#" * (pct // 2) + " " * (50 - pct // 2)
                    print(f"\r  [{bar}] {pct:3d}%", end="", flush=True)
        if total and got != total:
            raise OSError(f"incomplete download of {info.id}: got {got} of {total} bytes")
        if got < _min_bytes(info):
            raise OSError(
                f"download of {info.id} is only {got} bytes, expected about "
                f"{info.size_mb} MB"
            )
        if info.sha256 and digest.hexdigest() != info.sha256.lower():
            raise OSError(f"checksum mismatch for {info.id}")
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
        raise

    if show_progress:
        print(f"\r  [{'#' * 50}] 100%")
        print(f"Saved to {dest}")

    return dest
