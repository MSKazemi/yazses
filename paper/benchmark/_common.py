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
    #: The command line this artifact was produced by, redacted.
    #:
    #: The archive claimed to be reproducible while recording, for every one of its
    #: eighty-three files, the *script* and never its arguments -- and the arguments
    #: are what decide the numbers. `bench_wer.py` writes the same filename for
    #: `200 test-clean` and `500 test-other`; `bench_beam.py` writes it for
    #: `--grid=base.en:1,2,5` and for `--grid=tiny.en:1,2,5`, which is the pair whose
    #: disagreement decided ADR-v2-073; `bench_diarization.py` writes it with and
    #: without `--max-speakers 4`, the difference the AMI table turns on. A reader
    #: told only the script name cannot re-run any of them, so "reproduce it from the
    #: harness" was an instruction that could not be followed.
    argv: str = ""
    #: Which utterances were scored, not merely how many.
    #:
    #: Every artifact recorded `n_utterances: 200` and nothing about *which* 200.
    #: `librispeech_subset` is deterministic given the corpus -- sorted ids, sorted
    #: speakers, round-robin, no RNG -- but it skips an utterance whose `.flac` is
    #: absent and keeps going, so a host with a partially extracted corpus scores a
    #: *different* set and still reports 200. These numbers were taken on a laptop,
    #: two rented x86 boxes and three CI runners, and "reproducible across CPUs" was
    #: published off exactly that kind of cross-host comparison. A digest of the
    #: selected ids makes a divergence visible instead of silent; `n_missing` names
    #: its cause when it happens.
    corpus: dict | None = None


def _redact(text: str) -> str:
    """Strip the home directory and the login name out of a command line.

    Everything in `paper/results/` is published, and
    `tests/test_benchmark_results_are_archived.py` fails the build on `/home/<name>`,
    `/Users/<name>` or a bare login. The benchmarks were run on rented boxes where the
    corpus path began with the home directory every time, so the argv this records
    would carry one into git history on its first use if it were stored raw -- the
    exact leak that guard exists to prevent, arriving through a new door.

    Order matters: the real `$HOME` is replaced first so that a path *under* it keeps
    its tail (`$HOME/ami16_corpus`), and only then is the generic form applied to a
    path belonging to some other account.
    """
    import re

    home = os.path.expanduser("~")
    if home and home != "/":
        text = text.replace(home, "$HOME")
    text = re.sub(r"/home/[A-Za-z0-9_.-]+", "$HOME", text)
    text = re.sub(r"/Users/[A-Za-z0-9_.-]+", "$HOME", text)
    text = re.sub(r"[Cc]:\\+Users\\+[A-Za-z0-9_.-]+", "$HOME", text)
    user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    if len(user) > 2:
        text = re.sub(rf"\b{re.escape(user)}\b", "$USER", text)
    return text


def _argv() -> str:
    """This process's command line, shortened to the repository and redacted.

    `sys.argv[0]` is an absolute path to the script; the useful form is the one a
    reader can paste, which is the path relative to the repository root.
    """
    import shlex

    argv = list(sys.argv) or [""]
    try:
        argv[0] = Path(argv[0]).resolve().relative_to(REPO_ROOT).as_posix()
    except Exception:
        argv[0] = Path(argv[0]).name
    return _redact(shlex.join(argv))


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
        argv=_argv(),
        corpus=_LAST_SUBSET,
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


#: Set by `librispeech_subset` and read by `provenance()`. A module-level record
#: rather than a return value on purpose: eight `__main__` blocks would each have to
#: remember to thread it through, and that arrangement is what already failed for
#: `provenance` itself and again for `argv`. Stamping happens where the data is.
_LAST_SUBSET: dict | None = None


def subset_digest(utt_ids) -> str:
    """Stable 16-hex digest of an ordered utterance list."""
    import hashlib

    return hashlib.sha256("\n".join(utt_ids).encode("utf-8")).hexdigest()[:16]


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
        _record_subset(entries, n, split, stratified=False, tried=len(entries))
        return entries

    # Speaker-stratified round-robin (deterministic).
    by_speaker: dict[str, list[str]] = {}
    for utt_id in sorted(refs):
        by_speaker.setdefault(utt_id.split("-")[0], []).append(utt_id)
    speakers = sorted(by_speaker)
    out: list[tuple[str, Path, str, float]] = []
    idx = 0
    tried = 0
    while len(out) < n:
        progressed = False
        for spk in speakers:
            bucket = by_speaker[spk]
            if idx < len(bucket):
                progressed = True
                tried += 1
                e = _entry(bucket[idx])
                if e is not None:
                    out.append(e)
                    if len(out) >= n:
                        break
        if not progressed:  # exhausted every speaker
            break
        idx += 1
    _record_subset(out, n, split, stratified=True, tried=tried)
    return out


def _record_subset(entries, requested: int, split: str, *, stratified: bool, tried: int) -> None:
    """Remember what the last subset actually was, for `provenance()` to stamp."""
    global _LAST_SUBSET
    ids = [e[0] for e in entries]
    _LAST_SUBSET = {
        "dataset": f"LibriSpeech {split}",
        "requested_n": requested,
        "n": len(ids),
        "stratified": stratified,
        "sha256_16": subset_digest(ids),
        "first": ids[0] if ids else "",
        "last": ids[-1] if ids else "",
        # Non-zero means the corpus on this host is not the corpus the digest of a
        # peer artifact was taken over -- the failure this field exists to name.
        "n_missing": max(0, tried - len(ids)),
    }


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
    else:
        # `run_all.py` attaches a *shared* block so every file in one sweep names the
        # same machine and the same instant, and that is the right thing for the
        # machine half. The command line is not shared in the same way -- it is a fact
        # about this process, and stamping it only on the branch above would have left
        # every sweep-written artifact without the one field that says how to re-run
        # it. Filled in rather than overwritten, so a caller that already recorded a
        # more precise command keeps it.
        prov = payload["provenance"]
        if isinstance(prov, dict):
            fill = {}
            if not prov.get("argv"):
                fill["argv"] = _argv()
            if not prov.get("corpus") and _LAST_SUBSET:
                fill["corpus"] = _LAST_SUBSET
            if fill:
                payload = {**payload, "provenance": {**prov, **fill}}
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
