"""One registry of every model YazSes can use, and a pure ``ensure_model`` (#929, epic #928).

YazSes knows its models in five places that never met: the Whisper table in
``stt/download.py``, the GGUF table in ``commands/model_manager.py``, the Kokoro files in
``tts/download.py``, the sherpa files in ``recimport/download.py`` and the MediaPipe asset in
``gaze/download.py`` (plus the Silero VAD, which ships inside its wheel). This module reads
all of them **without changing them** and answers three questions per model: what is it, is it
on disk, and which feature owns it.

Two halves, both pure:

* :func:`build_registry` -- a read-only listing. Locations are injected, so a test points it at
  a tmp dir; the defaults resolve the real ones lazily, so a base install imports this module.
* :func:`ensure_model` -- decides what to do about one model under a policy
  (``auto`` | ``ask`` | ``never``). It takes ``is_cached`` and ``download`` as callables and
  never touches the network itself; the egress inventory (ADR-019) is unchanged because the
  only code that can fetch stays in the modules it already lists.

A config key for the download policy (proposed in ADR-035, not yet in ``config.py``) would
feed *policy*; adding it is an L3 change awaiting owner sign-off (ADR-030). Until then
callers pass ``"auto"``, which is today's behaviour. The Read-Back voice
(``tts/kokoro.py``) is the first fetch routed through :func:`ensure_model`; ADR-035 lists
the ones that are not yet.
"""
from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "KINDS",
    "POLICIES",
    "ModelEntry",
    "EnsureResult",
    "build_registry",
    "find_entry",
    "ensure_model",
    "remove_entry",
    "disk_usage",
]

KINDS: tuple[str, ...] = ("stt", "vad", "slm", "tts", "diarization", "gaze")
POLICIES: tuple[str, ...] = ("auto", "ask", "never")

#: Owning feature (as named by ``yazses features``) per kind.
_OWNERS = {
    "stt": "dictation",
    "vad": "meeting",
    "slm": "commands",
    "tts": "read-back",
    "diarization": "diarize",
    "gaze": "gaze",
}

#: Approximate download sizes in MB, for the ``ask`` message and ``model list``. Estimates for
#: the faster-whisper checkpoints, shown with "~"; an unknown name shows no size.
_STT_SIZE_MB = {
    "tiny": 75, "tiny.en": 75, "base": 141, "base.en": 141, "small": 464, "small.en": 464,
    "medium": 1400, "medium.en": 1400, "large": 2900, "large-v1": 2900, "large-v2": 2900,
    "large-v3": 2900, "large-v3-turbo": 1600, "turbo": 1600, "distil-small.en": 330,
    "distil-medium.en": 790, "distil-large-v2": 1500, "distil-large-v3": 1500,
    "distil-large-v3.5": 1500,
}


@dataclass(frozen=True)
class ModelEntry:
    kind: str
    name: str
    owner: str
    size_mb: int | None
    state: str  # "present" | "missing" | "bundled"
    #: What ``remove`` deletes (a directory for stt, files otherwise); empty for ``bundled``.
    paths: tuple[Path, ...] = ()
    #: Bytes on disk when present, else 0.
    disk_bytes: int = 0
    description: str = ""

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.name}"

    @property
    def present(self) -> bool:
        return self.state in ("present", "bundled")


@dataclass(frozen=True)
class EnsureResult:
    #: "ready" (already there) | "downloaded" | "missing" (not fetched; see message) | "failed"
    status: str
    kind: str
    name: str
    message: str = ""
    path: Path | None = None
    #: What *download* raised, when status is "failed".
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("ready", "downloaded")

    def raise_for_failure(self) -> None:
        """Re-raise what a failed download raised, unchanged; otherwise do nothing.

        For a caller whose own error handling already words a network failure. A
        ``missing`` result is a policy decision, not a failure, so it raises nothing.
        """
        if self.error is not None:
            raise self.error


def _size_of(paths: tuple[Path, ...]) -> int:
    total = 0
    for p in paths:
        try:
            if p.is_dir():
                total += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            elif p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def _stt_entries(hf_cache: Path) -> list[ModelEntry]:
    from yazses.stt.download import WHISPER_MODELS, is_cached, whisper_repo_id

    out: list[ModelEntry] = []
    for name in sorted(WHISPER_MODELS):
        repo = whisper_repo_id(name) or name
        folder = hf_cache / ("models--" + repo.replace("/", "--"))
        present = is_cached(name, hf_cache)
        paths = (folder,) if present and folder.exists() else ()
        out.append(ModelEntry(
            "stt", name, _OWNERS["stt"], _STT_SIZE_MB.get(name),
            "present" if present else "missing", paths, _size_of(paths),
            f"faster-whisper {name}",
        ))
    return out


def _slm_entries(slm_dir: Path) -> list[ModelEntry]:
    from yazses.commands.model_manager import MIN_SIZE_FRACTION, REGISTRY

    out: list[ModelEntry] = []
    for info in REGISTRY.values():
        f = slm_dir / info.filename
        try:
            ok = f.is_file() and f.stat().st_size >= info.size_mb * 1024 * 1024 * MIN_SIZE_FRACTION
        except OSError:
            ok = False
        paths = (f,) if ok else ()
        out.append(ModelEntry(
            "slm", info.id, _OWNERS["slm"], info.size_mb,
            "present" if ok else "missing", paths, _size_of(paths), info.description,
        ))
    return out


def _file_entry(kind: str, name: str, files: tuple[Path, ...], size_mb: int, desc: str) -> ModelEntry:
    ok = all(f.is_file() for f in files)
    paths = tuple(f for f in files if f.is_file())
    return ModelEntry(
        kind, name, _OWNERS[kind], size_mb, "present" if ok else "missing", paths,
        _size_of(paths), desc,
    )


def build_registry(
    *,
    hf_cache: Path | None = None,
    slm_dir: Path | None = None,
    tts_dir: Path | None = None,
    diarization_dir: Path | None = None,
    gaze_dir: Path | None = None,
) -> list[ModelEntry]:
    """Every model of every kind, with its on-disk state. Read-only; never downloads.

    Each directory argument, when given, replaces the real location (tests pass tmp dirs).
    """
    if hf_cache is None:
        from yazses.stt.download import hub_cache_dir

        hf_cache = hub_cache_dir()
    if slm_dir is None:
        from yazses.commands.model_manager import _CACHE_BASE

        slm_dir = _CACHE_BASE  # not models_dir(): listing must not create the directory
    if tts_dir is None:
        from yazses.tts.download import model_dir as tts_model_dir

        tts_dir = tts_model_dir()
    if diarization_dir is None:
        diarization_dir = _default_diarization_dir()
    if gaze_dir is None:
        from yazses.gaze.download import model_dir as gaze_model_dir

        gaze_dir = gaze_model_dir()

    from yazses.recimport.diarizer import _EMB_MODEL, _SEG_MODEL

    entries = _stt_entries(hf_cache)
    entries.append(ModelEntry(
        "vad", "silero", _OWNERS["vad"], 0, "bundled", (), 0,
        "Silero VAD ships inside the silero-vad wheel (optional `silero` extra); no download",
    ))
    entries += _slm_entries(slm_dir)
    entries.append(_file_entry(
        "tts", "kokoro",
        (tts_dir / "kokoro-v1.0.onnx", tts_dir / "voices-v1.0.bin"), 340,
        "Kokoro-82M int8 voice for the Read-Back Loop",
    ))
    entries.append(_file_entry(
        "diarization", "sherpa",
        (diarization_dir / _SEG_MODEL, diarization_dir / _EMB_MODEL), 45,
        "sherpa-onnx segmentation + speaker embedding",
    ))
    entries.append(_file_entry(
        "gaze", "face-landmarker", (gaze_dir / "face_landmarker.task",), 4,
        "MediaPipe FaceLandmarker",
    ))
    return entries


def _default_diarization_dir() -> Path:
    from yazses.platform import get_platform
    from yazses.recimport.diarizer import model_dir

    class _Fallback:
        model_dir = ""

    cfg: object = _Fallback()
    try:
        from yazses.config import load_config

        cfg = load_config(get_platform().paths.config_file).recimport
    except Exception:  # noqa: BLE001 -- a broken config must not break a listing
        pass
    return model_dir(cfg)


def find_entry(entries: list[ModelEntry], ident: str) -> ModelEntry | None:
    """Resolve ``kind:name`` or a bare name that is unambiguous across kinds."""
    ident = (ident or "").strip()
    for e in entries:
        if e.id == ident:
            return e
    matches = [e for e in entries if e.name == ident]
    return matches[0] if len(matches) == 1 else None


def remove_entry(entry: ModelEntry) -> list[Path]:
    """Delete what *entry* has on disk and return the paths removed.

    Touches only the paths the registry itself resolved, so a user's own ``[stt] model``
    directory is never in scope. A ``bundled`` or ``missing`` entry removes nothing.
    """
    removed: list[Path] = []
    for p in entry.paths:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink(missing_ok=True)
        removed.append(p)
    return removed


def disk_usage(entries: list[ModelEntry]) -> dict[str, int]:
    """Bytes on disk per kind (every kind present, zero when nothing is installed)."""
    usage = {k: 0 for k in KINDS}
    seen: set[tuple[Path, ...]] = set()
    for e in entries:
        if e.paths in seen:  # aliases (large / large-v3) share one cache folder
            continue
        seen.add(e.paths)
        usage[e.kind] += e.disk_bytes
    return usage


def _fetch_command(kind: str, name: str) -> str:
    """The command that fetches this model on purpose, or "" when YazSes has none.

    ``yazses model download`` knows Whisper short names and the intent-routing GGUFs
    only; pointing anyone else at it ends in "Unknown model".
    """
    if kind == "diarization":
        return "yazses transcribe --download-models"
    if kind == "slm":
        return f"yazses model download {name}"
    if kind == "stt":
        from yazses.stt.download import is_whisper_model

        if is_whisper_model(name):
            return f"yazses model download {name}"
    return ""


def ensure_model(
    kind: str,
    name: str,
    policy: str = "auto",
    *,
    is_cached: Callable[[str], bool],
    download: Callable[[str], Path | None],
    size_mb: int | None = None,
    manual_hint: str = "",
) -> EnsureResult:
    """Make *name* available, or say exactly why it is not -- under *policy*.

    * ``auto``  -- fetch it when absent (today's behaviour).
    * ``ask``   -- never fetch; report what is missing and its size so the caller can start
      anyway and tell the user, naming the command that fetches it (or *manual_hint* when
      YazSes has no such command for this model).
    * ``never`` -- never fetch; report the manual route (*manual_hint*, e.g. a model URL).

    Pure: the only side effects are whatever the injected *download* does, and it is called
    only under ``auto``. A *download* that raises an ``Exception`` yields ``failed``
    carrying the error and its text (the caller owns the wording of a network failure).
    """
    if kind not in KINDS:
        raise ValueError(f"unknown model kind {kind!r}; expected one of {', '.join(KINDS)}")
    if policy not in POLICIES:
        raise ValueError(f"unknown download policy {policy!r}; expected one of {', '.join(POLICIES)}")
    if is_cached(name):
        return EnsureResult("ready", kind, name)

    size = f" (~{size_mb} MB)" if size_mb else ""
    hint = f" Get it by hand: {manual_hint}" if manual_hint else ""
    if policy == "ask":
        command = _fetch_command(kind, name)
        route = f" Fetch it with: {command}" if command else hint
        return EnsureResult(
            "missing", kind, name,
            f"{kind} model {name!r}{size} is not on this machine. Nothing was downloaded."
            f"{route}",
        )
    if policy == "never":
        return EnsureResult(
            "missing", kind, name,
            f"{kind} model {name!r}{size} is not on this machine and downloads are off.{hint}",
        )
    try:
        path = download(name)
    except Exception as exc:  # noqa: BLE001 -- the caller words the failure
        return EnsureResult("failed", kind, name, str(exc), error=exc)
    return EnsureResult("downloaded", kind, name, path=path)
