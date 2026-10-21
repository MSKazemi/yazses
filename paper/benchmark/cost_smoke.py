"""Run the cost meter once on one short clip -- a check of the instrument, not a result.

PAPER2-ENERGY-001 (#506). `bench_latency.py` needs the LibriSpeech subset; this needs one
clip, so the CPU and energy plumbing can be exercised on any machine in seconds:

    uv run python paper/benchmark/cost_smoke.py --out /tmp/cost-smoke.json
    uv run python paper/benchmark/cost_smoke.py --out x.json --synthetic 3 --repeats 5
    uv run python paper/benchmark/cost_smoke.py --out x.json --fake-decoder

The default clip is the bundled ``data/librispeech-sample/jfk.wav``. The Whisper model is
loaded from the local cache only (``HF_HUB_OFFLINE=1`` is set before faster-whisper is
imported), so this never downloads. If the model is not cached, or ``--fake-decoder`` is
given, a *fake* decoder stands in -- deterministic numpy work proportional to the audio
length -- and the output says so under ``decoder.kind``. A fake run proves the meter, never
a model's cost.

``--out`` is required and has no default under ``paper/results/``: a smoke run on one clip
is not an archived measurement and must not look like one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from cost_meter import SCHEMA_VERSION, CostMeter, check_record, default_probes

from _common import REPO_ROOT, SAMPLE_RATE, load_audio, provenance

DEFAULT_CLIP = REPO_ROOT / "data" / "librispeech-sample" / "jfk.wav"


class FakeDecoder:
    """Stands in for an engine when no model is cached. Burns CPU, decodes nothing."""

    KIND = "fake"
    DESCRIPTION = "deterministic numpy FFT work proportional to audio length; not a speech decoder"

    def transcribe(self, audio: np.ndarray) -> str:
        frames = max(1, len(audio) // 400)
        x = np.resize(audio.astype(np.float32), (frames, 400))
        for _ in range(20):
            x = np.abs(np.fft.rfft(x, n=798, axis=1)).astype(np.float32)[:, :400]
        return ""


def synthetic_clip(seconds: float, seed: int = 0) -> np.ndarray:
    """A speech-band noise burst. Whisper may transcribe nothing from it; the cost is real."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    env = 0.5 * (1 + np.sin(2 * np.pi * 3.0 * t))  # syllable-rate amplitude envelope
    return (0.05 * env * rng.standard_normal(n)).astype(np.float32)


def _load_engine(model: str, fake: bool, meter: CostMeter):
    """Return ``(engine, decoder_info)``, timing the load inside the meter's span."""
    if fake:
        with meter.span():
            engine = FakeDecoder()
        return engine, {"kind": FakeDecoder.KIND, "description": FakeDecoder.DESCRIPTION,
                        "why": "--fake-decoder given"}
    os.environ["HF_HUB_OFFLINE"] = "1"  # cache only; this script must never download
    try:
        from yazses.stt.faster_whisper import FasterWhisperEngine

        with meter.span():
            engine = FasterWhisperEngine(model_name=model)
        return engine, {"kind": "faster-whisper", "model": model, "compute_type": "int8"}
    except Exception as exc:  # not cached, or the stt extra is not installed
        with meter.span():
            engine = FakeDecoder()
        return engine, {"kind": FakeDecoder.KIND, "description": FakeDecoder.DESCRIPTION,
                        "why": f"{model} could not be loaded offline: {type(exc).__name__}"}


def run(clip: np.ndarray, clip_info: dict, *, model: str, repeats: int, fake: bool) -> dict:
    audio_s = len(clip) / SAMPLE_RATE
    load_meter = CostMeter(default_probes())
    load_meter.begin()
    engine, decoder = _load_engine(model, fake, load_meter)
    load_cost = check_record(load_meter.end())

    decode_meter = CostMeter(default_probes())
    decode_meter.begin()
    text = ""
    for _ in range(repeats):
        with decode_meter.span(audio_s=audio_s):
            out = engine.transcribe(clip)
        text = out if isinstance(out, str) else str(getattr(out, "text", out))
    decode_cost = check_record(decode_meter.end())
    return {
        "cost_schema_version": SCHEMA_VERSION,
        "kind": "cost_smoke",
        "note": "instrument check on one clip; not a result, not comparable across machines",
        "clip": clip_info,
        "decoder": decoder,
        "repeats": repeats,
        "transcript": text[:200],
        "load_cost": load_cost,
        "decode_cost": decode_cost,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True, help="where to write the JSON")
    ap.add_argument("--wav", type=Path, default=DEFAULT_CLIP, help="16 kHz mono clip")
    ap.add_argument("--synthetic", type=float, metavar="SECONDS",
                    help="use a synthetic noise clip of this length instead of --wav")
    ap.add_argument("--model", default="tiny.en")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--fake-decoder", action="store_true")
    args = ap.parse_args(argv)
    if args.repeats < 1:
        ap.error("--repeats must be >= 1")

    if args.synthetic:
        clip = synthetic_clip(args.synthetic)
        info = {"kind": "synthetic", "seconds": args.synthetic, "seed": 0}
    else:
        clip = load_audio(args.wav)
        try:
            shown = args.wav.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            shown = args.wav.name  # never record a home-directory path
        info = {"kind": "file", "path": shown,
                "sha256": hashlib.sha256(args.wav.read_bytes()).hexdigest()}
    info["audio_s"] = round(len(clip) / SAMPLE_RATE, 3)

    t0 = time.perf_counter()
    result = run(clip, info, model=args.model, repeats=args.repeats, fake=args.fake_decoder)
    result["provenance"] = provenance(datetime.now(timezone.utc).isoformat(timespec="seconds"))
    result["elapsed_s"] = round(time.perf_counter() - t0, 3)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    d = result["decode_cost"]
    print(f"[cost] decoder={result['decoder']['kind']} audio={info['audio_s']}s x{args.repeats}: "
          f"core-s/audio-s={d['cpu_core_seconds_per_audio_s']} rtf={d['rtf']} "
          f"cores-busy={d['mean_cores_busy']}")
    for name, r in d["energy"].items():
        val = r["energy_joules"] if r["available"] else f"null ({r['reason']})"
        print(f"[cost] energy.{name}: {val}")
    print(f"[cost] wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
