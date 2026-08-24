"""Shared helpers for the YazSes benchmark harness (arXiv paper).

Provenance capture, LibriSpeech subset loading, and audio I/O. Every result JSON
embeds a provenance block so a number is never quoted without the conditions it was
measured under (design/vision/PRINCIPLES.md).
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
PAPER_DIR = REPO_ROOT / "paper"
DATA_DIR = PAPER_DIR / "data"
RESULTS_DIR = PAPER_DIR / "results"
LIBRISPEECH_DIR = DATA_DIR / "LibriSpeech" / "test-clean"

# The splits a WER bench may be pointed at. `test-clean` is read audiobook speech
# recorded in quiet conditions and is the split every published Whisper number uses,
# which is exactly why it cannot be the only one measured here: docs/benchmarks.md
# has always warned that "your dictation WER will be worse than this" without ever
# measuring anything that was worse. `test-other` is the same corpus, same readers'
# format, drawn from the harder half of the speaker pool -- so it answers "how much
# worse" on a difference that is only the audio.
LIBRISPEECH_SPLITS = ("test-clean", "test-other")


def librispeech_dir(split: str = "test-clean") -> Path:
    """Directory for one LibriSpeech split, validated.

    An unknown split would otherwise surface as a `FileNotFoundError` naming a path
    the reader has to reverse-engineer, and -- worse -- a *typo'd* one could silently
    match nothing and score zero utterances.
    """
    if split not in LIBRISPEECH_SPLITS:
        raise ValueError(
            f"unknown LibriSpeech split {split!r}; expected one of {LIBRISPEECH_SPLITS}"
        )
    return DATA_DIR / "LibriSpeech" / split

SAMPLE_RATE = 16000


def _cpu_model() -> str:
    """Name the CPU on every OS the benchmarks run on.

    This used to shell out to ``lscpu`` and fall back to ``platform.processor()``.
    ``lscpu`` exists only on Linux, and the fallback answers ``"arm"`` on macOS and
    an empty string on some Windows builds -- so a cross-machine results table would
    have stamped several different hosts with the same uninformative name. Latency
    and RTF are machine-specific and may never be merged across hosts (see
    ``docs/benchmarks.md``), which is exactly the comparison this field exists to
    keep honest, so each OS gets the query that actually answers it.
    """
    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, check=False,
            ).stdout.strip()
            if out:
                return out
        elif sys.platform == "win32":
            # The registry rather than `wmic`: wmic is deprecated and absent from
            # recent Windows images, so the subprocess would simply not be found.
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            try:
                value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            finally:
                winreg.CloseKey(key)
            if value:
                return str(value).strip()
        else:
            out = subprocess.run(
                ["lscpu"], capture_output=True, text=True, check=False
            ).stdout
            for line in out.splitlines():
                if line.strip().startswith("Model name:"):
                    return line.split(":", 1)[1].strip()
    except Exception:  # pragma: no cover - best effort
        pass
    # platform.machine() is the more useful of the two on macOS/Windows, where
    # platform.processor() is often "arm" or "".
    return platform.processor() or platform.machine() or "unknown"


def _pkg_version(name: str) -> str:
    import importlib.metadata as m

    try:
        return m.version(name)
    except Exception:  # pragma: no cover
        return "unknown"


@dataclass
class Provenance:
    """Everything needed to interpret a measurement."""

    timestamp: str
    cpu_model: str
    logical_cpus: int
    ram_gb: float
    os: str
    kernel: str
    python: str
    faster_whisper: str
    yazses: str
    numpy: str
    # CTranslate2, not faster-whisper, chooses the int8 kernels and the order the
    # partial sums are reduced in -- so it, the thread count it was given and the
    # ISA it dispatched to are what decide whether two hosts agree on a WER.
    ctranslate2: str
    omp_num_threads: str
    load_average_1m: float
    compute_type: str = "int8"
    device: str = "cpu"


def provenance(timestamp: str) -> dict:
    import psutil

    p = Provenance(
        timestamp=timestamp,
        cpu_model=_cpu_model(),
        logical_cpus=os.cpu_count() or 0,
        ram_gb=round(psutil.virtual_memory().total / 1e9, 1),
        os=_os_pretty(),
        kernel=platform.release(),
        python=platform.python_version(),
        faster_whisper=_pkg_version("faster-whisper"),
        yazses=_pkg_version("yazses"),
        numpy=np.__version__,
        ctranslate2=_pkg_version("ctranslate2"),
        omp_num_threads=os.environ.get("OMP_NUM_THREADS", "unset"),
        load_average_1m=_load_average(),
    )
    return asdict(p)


def _load_average() -> float:
    """One-minute load average, or ``-1.0`` where the OS has no such notion.

    Recorded because a benchmark that reports seconds is only meaningful on a box
    that was not busy, and "the box was idle" is a claim the artifact should carry
    rather than something the person reading it has to take on trust. A dedicated
    machine is no protection: the contention that invalidated the first run of this
    matrix was created by other jobs the same operator started on the same host.
    """
    try:
        return round(os.getloadavg()[0], 2)  # not available on Windows
    except (AttributeError, OSError):
        return -1.0


def _os_pretty() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except Exception:  # pragma: no cover
        pass
    return platform.platform()


def load_audio(flac_path: Path) -> np.ndarray:
    """Load a FLAC file as float32 mono at 16 kHz (LibriSpeech is already 16 kHz)."""
    import soundfile as sf

    audio, sr = sf.read(str(flac_path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    assert sr == SAMPLE_RATE, f"expected {SAMPLE_RATE} Hz, got {sr}"
    return audio


def librispeech_subset(
    n: int, stratified: bool = True, split: str = "test-clean"
) -> list[tuple[str, Path, str, float]]:
    """Return a deterministic subset of a LibriSpeech split.

    Each entry is ``(utt_id, flac_path, reference_text, duration_seconds)``.

    ``stratified=True`` (default) draws a **speaker-stratified** sample: it
    round-robins across all speakers (sorted), taking one utterance from each in
    turn until ``n`` are collected, so the subset spans the corpus's speakers
    rather than clustering on the lowest-numbered ids. Fully deterministic (no RNG).
    ``stratified=False`` keeps the legacy "first ``n`` by sorted id" behaviour
    (used for timing-only benches where speaker mix is irrelevant).

    ``split`` selects the LibriSpeech split; see `LIBRISPEECH_SPLITS`. It is a
    parameter rather than a module constant because a number measured on one split
    and quoted as the other is the single cheapest way to make this page wrong, so
    the split travels with the call and lands in the result JSON's config block.
    """
    import soundfile as sf

    root = librispeech_dir(split)
    if not root.exists():
        raise FileNotFoundError(
            f"LibriSpeech {split} not found at {root}. Download "
            f"https://www.openslr.org/resources/12/{split}.tar.gz "
            "into paper/data/ and extract it."
        )
    refs: dict[str, str] = {}
    for trans in root.rglob("*.trans.txt"):
        for line in trans.read_text().splitlines():
            utt_id, _, text = line.partition(" ")
            refs[utt_id] = text

    def _entry(utt_id: str):
        parts = utt_id.split("-")  # e.g. 7127-75946-0000
        flac = root / parts[0] / parts[1] / f"{utt_id}.flac"
        if not flac.exists():
            return None
        info = sf.info(str(flac))
        return (utt_id, flac, refs[utt_id], float(info.frames) / info.samplerate)

    if not stratified:
        entries: list[tuple[str, Path, str, float]] = []
        for utt_id in sorted(refs):
            e = _entry(utt_id)
            if e is not None:
                entries.append(e)
            if len(entries) >= n:
                break
        return entries

    # Speaker-stratified round-robin (deterministic).
    by_speaker: dict[str, list[str]] = {}
    for utt_id in sorted(refs):
        by_speaker.setdefault(utt_id.split("-")[0], []).append(utt_id)
    speakers = sorted(by_speaker)
    out: list[tuple[str, Path, str, float]] = []
    idx = 0
    while len(out) < n:
        progressed = False
        for spk in speakers:
            bucket = by_speaker[spk]
            if idx < len(bucket):
                progressed = True
                e = _entry(bucket[idx])
                if e is not None:
                    out.append(e)
                    if len(out) >= n:
                        break
        if not progressed:  # exhausted every speaker
            break
        idx += 1
    return out


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=float), q))


def write_result(name: str, payload: dict) -> Path:
    """Write one result, stamping provenance if the caller did not.

    `run_all.py` attaches a *shared* block so every file in one sweep names the same
    machine and the same instant, and that stays. But a single bench run straight from
    the command line -- the documented way to re-measure one thing -- went through here
    without one, and overwrote the good file with an anonymous one. `vad.json` and
    `streaming.json` were both sitting in `paper/results/` with no record of the CPU,
    the OS or the library versions they came from, which makes them numbers rather than
    measurements. Stamping at the single chokepoint is what stops the next one; asking
    eight `__main__` blocks to remember is the arrangement that already failed.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if "provenance" not in payload:
        import time

        payload = {
            "provenance": provenance(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            **payload,
        }
    path = RESULTS_DIR / f"{name}.json"
    text = json.dumps(payload, indent=2, sort_keys=False)
    _archive_previous(path, text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _archive_previous(path: Path, new_text: str) -> Path | None:
    """Copy `path` under `results/history/` when `new_text` would change it.

    **A re-run must never destroy the previous measurement.** Every published table is
    keyed to a fixed filename, so a second run of the same benchmark overwrites the first
    -- fine when the numbers agree, and silently destructive when they do not. They did
    not: re-running the `test-other` matrix moved `large-v3` by 2.83 points, and by then
    the run this page had been quoting survived only in a console log on a VM. Identical
    content is *not* archived, because re-running a reproducible benchmark is the normal
    case and should not accumulate copies of the same numbers.

    The timestamp comes from the displaced file's own provenance rather than the clock,
    so the copy is named for when it was measured, not for when it was moved aside.

    Never raises into a benchmark: losing an archive copy is bad, losing a two-hour
    decode because the archive step tripped over a permission is worse.
    """
    try:
        if not path.exists():
            return None
        old_text = path.read_text(encoding="utf-8")
        if old_text == new_text:
            return None
        stamp = "unstamped"
        try:
            stamp = json.loads(old_text).get("provenance", {}).get("timestamp") or stamp
        except (ValueError, AttributeError):
            pass
        stamp = "".join(c if c.isalnum() else "-" for c in str(stamp))
        history = RESULTS_DIR / "history"
        history.mkdir(parents=True, exist_ok=True)
        # `name` may carry a subdirectory (`probes/x`); flatten it so `history/` stays one
        # level deep and a nested name cannot write outside it.
        flat = path.relative_to(RESULTS_DIR).as_posix().removesuffix(".json").replace("/", "-")
        dest = history / f"{flat}-{stamp}.json"
        if not dest.exists():
            dest.write_text(old_text, encoding="utf-8")
        return dest
    except OSError:
        return None
