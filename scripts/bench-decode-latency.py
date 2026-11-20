"""Release-to-transcript latency harness for hold-to-talk dictation (faster-whisper).

Measures the part of a dictation the user waits for after letting go of the key and
before post-processing starts: the pre-decode audio work the daemon does on the burst,
and the decode itself -- broken into feature extraction, encoder and decoder -- for a
grid of decoder settings. Three modes:

``cold``
    N fresh processes, each timing ``import faster_whisper``, the model load from the
    local cache, the first and later decodes, and the first and later Silero
    speech-presence checks. This is what the first dictation after a daemon start
    (or after an ``[stt] idle_unload_s`` reload) pays.
``warm``
    One process, every variant decoded round-robin (interleaved, so a load spike on a
    shared machine lands on every variant alike), ``--reps`` times each. Every
    variant's transcript is compared with the baseline's, so a "faster" setting that
    changes the text is reported as such rather than as a free win.
``idle``
    A decode after ``--gaps`` seconds of idle, to see whether a model left resident but
    unused decodes slower than a hot one.

Each measurement records ``os.getloadavg()``. Results are written as JSON with the
provenance ADR-033 asks for (commit, versions, model digest, CPU, settings).
Offline: the model is loaded with ``local_files_only=True`` and nothing is fetched.

Usage::

    python scripts/bench-decode-latency.py warm --audio data/librispeech-sample/jfk.wav
    python scripts/bench-decode-latency.py cold --reps 15 --json-out cold.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

#: The prompt a default install decodes with (`stt.vocabulary.BUILTIN_PROMPT`).
DEFAULT_PROMPT = "The app is called YazSes."
#: A long personal vocabulary, to price the prompt length. Synthetic.
LONG_PROMPT = (
    "Kubernetes, PostgreSQL, ydotool, Wayland, PipeWire, CTranslate2, faster-whisper, "
    "Moonshine, Parakeet, Silero, ONNX, LibriSpeech, numpy, pytest, mypy, ruff, "
    "GitHub, Codeberg, Flatpak, Chocolatey, Homebrew, systemd, journalctl, tmux, "
    "Neovim, VS Code, JetBrains, Docker, Podman, Ansible, Terraform, Grafana. "
    + DEFAULT_PROMPT
)
#: Clip lengths cut from the fixture, in seconds (None = whole file).
CLIPS: tuple[float | None, ...] = (2.5, 5.0, None)
#: The daemon's default `[accessibility] pre_speech_padding_ms`.
LEAD_MS = 300


def nearest_rank(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile (same definition as `yazses.stt.latency.percentile`)."""
    ordered = sorted(values)
    rank = math.ceil(round(fraction * len(ordered), 9))
    rank = min(max(rank, 1), len(ordered))
    return float(ordered[rank - 1])


def summarise(ms: list[float]) -> dict[str, float | int]:
    if not ms:
        return {"n": 0}
    return {
        "n": len(ms),
        "p50_ms": round(nearest_rank(ms, 0.5), 1),
        "p95_ms": round(nearest_rank(ms, 0.95), 1),
        "min_ms": round(min(ms), 1),
    }


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SystemExit(f"{path}: expected 16 kHz mono 16-bit PCM")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def with_lead(audio: np.ndarray, lead_ms: int = LEAD_MS) -> np.ndarray:
    """What `core/daemon.py` hands the decoder: zeros, then the burst."""
    if lead_ms <= 0:
        return audio
    return np.concatenate([np.zeros(int(lead_ms * 16), dtype=audio.dtype), audio])


def model_path(name: str) -> Path | None:
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    snaps = sorted((hub / f"models--Systran--faster-whisper-{name}" / "snapshots").glob("*"))
    return snaps[-1] if snaps else None


def provenance(model: str) -> dict[str, Any]:
    from importlib import metadata

    versions: dict[str, str | None] = {"python": platform.python_version()}
    for dist in ("faster-whisper", "ctranslate2", "numpy", "onnxruntime"):
        try:
            versions[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            versions[dist] = None
    snap = model_path(model)
    digest = None
    if snap is not None and (snap / "model.bin").exists():
        digest = hashlib.sha256((snap / "model.bin").read_bytes()).hexdigest()
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent,
            capture_output=True, text=True, timeout=10, check=False).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        commit = None
    cpu = platform.processor()
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {
        "commit": commit, "versions": versions, "model": model,
        "model_revision": snap.name if snap else None, "model_sha256": digest,
        "cpu": cpu, "logical_cpus": os.cpu_count(), "os": platform.platform(),
        "date": time.strftime("%Y-%m-%d"),
    }


def load_model(name: str, cpu_threads: int = 0):
    from faster_whisper import WhisperModel

    extra = {"cpu_threads": cpu_threads} if cpu_threads > 0 else {}
    return WhisperModel(name, device="cpu", compute_type="int8",
                        local_files_only=True, **extra)


class _TimedExtractor:
    """Proxy for `model.feature_extractor` that times each call."""

    def __init__(self, inner, sink: dict[str, float]) -> None:
        self._inner = inner
        self._sink = sink

    def __call__(self, *a, **k):
        t = time.perf_counter()
        try:
            return self._inner(*a, **k)
        finally:
            self._sink["features"] += time.perf_counter() - t

    def __getattr__(self, name):
        return getattr(self._inner, name)


def instrument(model) -> dict[str, float]:
    """Time feature extraction and encoder calls on *model* (the rest is decoding)."""
    sink = {"features": 0.0, "encode": 0.0}
    model.feature_extractor = _TimedExtractor(model.feature_extractor, sink)
    raw_encode = model.encode

    def encode(features):
        t = time.perf_counter()
        try:
            return raw_encode(features)
        finally:
            sink["encode"] += time.perf_counter() - t

    model.encode = encode
    return sink


def decode(model, audio: np.ndarray, kwargs: dict) -> tuple[str, float]:
    t = time.perf_counter()
    segments, _ = model.transcribe(audio, **kwargs)
    text = " ".join(s.text.strip() for s in segments).strip()
    return text, (time.perf_counter() - t) * 1000.0


# ---- cold -------------------------------------------------------------------------------

def _cold_child(model_name: str, audio_path: str, warm: bool) -> None:
    out: dict[str, Any] = {"load_before": os.getloadavg()[0], "warm_up": warm}
    t = time.perf_counter()
    import faster_whisper  # noqa: F401
    out["import_ms"] = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    model = load_model(model_name)
    out["model_load_ms"] = (time.perf_counter() - t) * 1000
    audio = with_lead(load_wav(Path(audio_path))[: int(5.0 * 16000)])
    out["warm_up_ms"] = 0.0
    if warm:
        # The candidate that was measured and rejected for the decoder (a bounded,
        # discarded decode of 1 s of silence), plus what the daemon does ship: priming
        # the speech-presence detector (`audio.speech_presence.prime_detector`).
        from yazses.audio.speech_presence import SPEECH_THRESHOLD
        from yazses.recimport.audio_io import holds_no_speech as _hns

        t = time.perf_counter()
        segs, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language="en",
                                   temperature=0.0, max_new_tokens=4)
        for _ in segs:
            pass
        _hns(np.zeros(8000, dtype=np.float32), 16000, threshold=SPEECH_THRESHOLD)
        out["warm_up_ms"] = (time.perf_counter() - t) * 1000
    from yazses.recimport.audio_io import holds_no_speech
    for i in (1, 2):
        t = time.perf_counter()
        holds_no_speech(audio, 16000, threshold=0.3)
        out[f"vad{i}_ms"] = (time.perf_counter() - t) * 1000
    kw = {"language": "en", "initial_prompt": DEFAULT_PROMPT}
    texts = []
    for i in (1, 2, 3):
        text, ms = decode(model, audio, kw)
        out[f"decode{i}_ms"] = ms
        texts.append(text)
    out["identical"] = len(set(texts)) == 1
    out["load_after"] = os.getloadavg()[0]
    print(json.dumps(out))


def run_cold(args) -> dict[str, Any]:
    """Fresh processes, alternating without and with the post-load warm-up (A/B)."""
    rows = []
    for i in range(args.reps * 2):
        warm = bool(i % 2)
        cmd = [sys.executable, __file__, "_cold_child", "--model", args.model,
               "--audio", str(args.audio)] + (["--warm"] if warm else [])
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True,
                              env={**os.environ, "HF_HUB_OFFLINE": "1"})
        row = json.loads(proc.stdout.strip().splitlines()[-1])
        rows.append(row)
        print(f"cold {i + 1}/{args.reps * 2} warm={warm}: load {row['model_load_ms']:.0f} "
              f"ms, warm-up {row['warm_up_ms']:.0f}, decode1 {row['decode1_ms']:.0f}, "
              f"decode2 {row['decode2_ms']:.0f}, vad1 {row['vad1_ms']:.0f}, vad2 "
              f"{row['vad2_ms']:.1f} (load avg {row['load_before']:.2f})", flush=True)
    keys = ["import_ms", "model_load_ms", "warm_up_ms", "vad1_ms", "vad2_ms",
            "decode1_ms", "decode2_ms", "decode3_ms"]
    out: dict[str, Any] = {}
    for label, warm in (("no_warm_up", False), ("warm_up", True)):
        sub = [r for r in rows if r["warm_up"] is warm]
        out[label] = {
            "summary": {k: summarise([r[k] for r in sub]) for k in keys},
            "load_avg_median": round(float(np.median([r["load_before"] for r in sub])), 2),
            "load_avg_max": round(float(max(r["load_before"] for r in sub)), 2),
            "all_identical": all(r["identical"] for r in sub),
        }
    out["rows"] = rows
    return out


# ---- warm -------------------------------------------------------------------------------

def _variants(prompt: str) -> list[tuple[str, int, dict, int]]:
    """(name, cpu_threads, kwargs, lead_ms). The first is the shipped baseline."""
    base = {"language": "en", "initial_prompt": prompt}
    return [
        ("baseline", 0, dict(base), LEAD_MS),
        ("no_lead", 0, dict(base), 0),
        ("no_prompt", 0, {"language": "en"}, LEAD_MS),
        ("long_prompt", 0, {**base, "initial_prompt": LONG_PROMPT}, LEAD_MS),
        ("beam1", 0, {**base, "beam_size": 1}, LEAD_MS),
        ("beam2", 0, {**base, "beam_size": 2}, LEAD_MS),
        ("without_timestamps", 0, {**base, "without_timestamps": True}, LEAD_MS),
        ("vad_filter", 0, {**base, "vad_filter": True}, LEAD_MS),
        ("threads1", 1, dict(base), LEAD_MS),
        ("threads2", 2, dict(base), LEAD_MS),
        ("threads4", 4, dict(base), LEAD_MS),
    ]


def run_warm(args) -> dict[str, Any]:
    full = load_wav(args.audio)
    clips = {
        (f"{c:g}s" if c else f"{full.size / 16000:g}s"): (full[: int(c * 16000)] if c else full)
        for c in CLIPS
    }
    wanted = set(args.only.split(",")) if args.only else None
    variants = [v for v in _variants(DEFAULT_PROMPT) if wanted is None or v[0] in wanted
                or v[0] == "baseline"]
    models = {th: load_model(args.model, th) for th in sorted({v[1] for v in variants})}
    sinks = {th: instrument(m) for th, m in models.items()}
    # Warm every model once on every clip, untimed.
    for clip in clips.values():
        for th, m in models.items():
            decode(m, with_lead(clip), {"language": "en"})
    results: dict[str, dict[str, Any]] = {}
    for rep in range(args.reps):
        for cname, clip in clips.items():
            for name, th, kw, lead in variants:
                sink = sinks[th]
                sink["features"] = sink["encode"] = 0.0
                load = os.getloadavg()[0]
                text, ms = decode(models[th], with_lead(clip, lead), kw)
                cell = results.setdefault(f"{cname}/{name}", {
                    "total": [], "features": [], "encode": [], "load": [], "texts": set()})
                cell["total"].append(ms)
                cell["features"].append(sink["features"] * 1000)
                cell["encode"].append(sink["encode"] * 1000)
                cell["load"].append(load)
                cell["texts"].add(text)
        print(f"warm rep {rep + 1}/{args.reps} done (load avg {os.getloadavg()[0]:.2f})",
              flush=True)
    out: dict[str, Any] = {}
    for key, cell in results.items():
        cname = key.split("/")[0]
        base_texts = results[f"{cname}/baseline"]["texts"]
        decode_only = [t - f - e for t, f, e in
                       zip(cell["total"], cell["features"], cell["encode"], strict=True)]
        out[key] = {
            "total": summarise(cell["total"]),
            "features": summarise(cell["features"]),
            "encode": summarise(cell["encode"]),
            "decoder": summarise(decode_only),
            "load_avg_median": round(float(np.median(cell["load"])), 2),
            "load_avg_max": round(float(max(cell["load"])), 2),
            "deterministic": len(cell["texts"]) == 1,
            "same_text_as_baseline": cell["texts"] == base_texts,
            "texts": sorted(cell["texts"]),
        }
    return out


# ---- predecode --------------------------------------------------------------------------

def run_predecode(args) -> dict[str, Any]:
    """The daemon's per-burst audio work between `recorder.stop()` and the decode call.

    Default config: chunk concatenation, the level reads, the calibrated energy gate,
    the Silero speech-presence check (warm), the 300 ms zero lead-in, the prompt merge.
    """
    from yazses.audio.speech_presence import SPEECH_THRESHOLD
    from yazses.audio.vad_calibrated import is_silent_calibrated
    from yazses.config import AccessibilityConfig
    from yazses.recimport.audio_io import holds_no_speech
    from yazses.stt.vocabulary import merge_initial_prompt

    acc = AccessibilityConfig()
    burst = load_wav(args.audio)[: int(5.0 * 16000)]
    # PortAudio's callback hands over small blocks; 512 frames is a typical size.
    chunks = [burst[i:i + 512].copy() for i in range(0, burst.size, 512)]
    holds_no_speech(burst, 16000, threshold=SPEECH_THRESHOLD)  # load Silero first
    stages: dict[str, Any] = {
        "concatenate_chunks": lambda: np.concatenate(chunks),
        "level_reads_x3": lambda: [float(np.abs(burst).mean()) for _ in range(3)],
        "energy_gate": lambda: is_silent_calibrated(burst, acc),
        "speech_presence_silero": lambda: holds_no_speech(burst, 16000,
                                                          threshold=SPEECH_THRESHOLD),
        "lead_in_300ms": lambda: with_lead(burst),
        "prompt_merge": lambda: merge_initial_prompt("", language="en"),
    }
    out: dict[str, Any] = {}
    reps = max(args.reps, 15) * 20
    times: dict[str, list[float]] = {k: [] for k in stages}
    for _ in range(reps):
        for name, fn in stages.items():  # interleaved, like the warm grid
            t = time.perf_counter()
            fn()
            times[name].append((time.perf_counter() - t) * 1000)
    for name, ms in times.items():
        out[name] = {"n": len(ms), "p50_ms": round(nearest_rank(ms, 0.5), 3),
                     "p95_ms": round(nearest_rank(ms, 0.95), 3)}
    out["load_avg"] = os.getloadavg()[0]
    return out


# ---- idle -------------------------------------------------------------------------------

def run_idle(args) -> dict[str, Any]:
    audio = with_lead(load_wav(args.audio)[: int(5.0 * 16000)])
    model = load_model(args.model)
    kw = {"language": "en", "initial_prompt": DEFAULT_PROMPT}
    decode(model, audio, kw)
    gaps = [float(g) for g in args.gaps.split(",")]
    rows: dict[str, dict[str, list[float]]] = {f"{g:g}s": {"ms": [], "load": []} for g in gaps}
    for rep in range(args.reps):
        for g in gaps:
            decode(model, audio, kw)  # re-heat, then rest for the gap
            time.sleep(g)
            load = os.getloadavg()[0]
            _, ms = decode(model, audio, kw)
            rows[f"{g:g}s"]["ms"].append(ms)
            rows[f"{g:g}s"]["load"].append(load)
        print(f"idle rep {rep + 1}/{args.reps}: " + ", ".join(
            f"{k} {v['ms'][-1]:.0f} ms" for k, v in rows.items()), flush=True)
    return {k: {**summarise(v["ms"]), "load_avg_median": round(float(np.median(v["load"])), 2)}
            for k, v in rows.items()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("mode", choices=["cold", "warm", "idle", "predecode", "_cold_child"])
    p.add_argument("--model", default="base.en")
    p.add_argument("--audio", type=Path,
                   default=Path(__file__).resolve().parent.parent
                   / "data" / "librispeech-sample" / "jfk.wav")
    p.add_argument("--reps", type=int, default=15)
    p.add_argument("--only", default="", help="comma-separated warm variants")
    p.add_argument("--gaps", default="0,10,30", help="idle gaps in seconds")
    p.add_argument("--json-out", type=Path)
    p.add_argument("--warm", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if args.mode == "_cold_child":
        _cold_child(args.model, str(args.audio), args.warm)
        return 0
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    runner = {"cold": run_cold, "warm": run_warm, "idle": run_idle,
              "predecode": run_predecode}[args.mode]
    result = {"provenance": provenance(args.model), "mode": args.mode, "reps": args.reps,
              "audio": str(args.audio), "result": runner(args)}
    text = json.dumps(result, indent=2, default=sorted)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
