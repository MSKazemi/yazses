#!/usr/bin/env python3
"""Moonshine v1 (`useful-moonshine-onnx`) against `moonshine-voice` v2, under ADR-033.

A human-run measurement for item M1 of the 2026-11-19 start plans. ADR-033 (proposed)
forbids swapping a model or engine dependency without a pinned, matched measurement, and
this script is the measurement. It changes nothing in YazSes: `moonshine-voice` is **not**
a YazSes dependency, and nothing under `src/` imports it.

Three subcommands:

``run``      Score one `moonshine-voice` arch on a WAV/TXT corpus. It drives
             ``scripts/bench-stt.py`` with an in-script engine, so the fallback check,
             the file accounting, the normaliser and the JSON schema are the very ones the
             v1 row uses. Optionally (``--streaming``) it also replays every file through
             the native streaming API and records release-to-final time, partial counts
             and prefix retractions.
``digest``   Write a SHA-256 manifest of a model (or, with ``--field corpus``, a corpus)
             directory into a run JSON. Use it for the v1 row, whose weights live in the
             Hugging Face cache; ``run`` records both for the v2 row itself.
``compare``  Pair two or more run JSONs by file and print WER, a paired bootstrap 95 %
             interval on the WER difference, and decode p50/p95. Refuses unmatched
             corpora, different normalisers, fallbacks and partial coverage.

Typical session, on the ADR-033 reference machine, with **separate** environments so the
v2 package never enters the YazSes environment::

    # v1, from the YazSes environment
    uv run python scripts/bench-stt.py CORPUS --engine moonshine --model moonshine/base \\
        --json-out v1-base.json
    uv run python scripts/bench-moonshine-v2.py digest \\
        ~/.cache/huggingface/hub/models--UsefulSensors--moonshine --into v1-base.json
    uv run python scripts/bench-moonshine-v2.py digest CORPUS --field corpus --into v1-base.json

    # v2, from a throw-away venv: pip install moonshine-voice==0.1.6 jiwer numpy av
    #   (plus whisper-normalizer, so both rows use the same normaliser)
    python scripts/bench-moonshine-v2.py run CORPUS --arch small-streaming --fetch \\
        --streaming --json-out v2-small.json

    uv run python scripts/bench-moonshine-v2.py compare v1-base.json v2-small.json

``--fetch`` is the only network step. It downloads the English model from
``download.moonshine.ai`` (the package's own CDN, *not* Hugging Face) and is never
implied: without it ``--model-dir`` must name an already-prepared directory (ADR-033
item 6, "explicit authorized local dataset/model preparation"). Only English is accepted:
the non-English legacy checkpoints are under the Moonshine Community License, which the
model-manifest licence process has not cleared.

Exit codes follow ``bench-stt.py``: 2 fallback, 3 partial coverage, 4 a ``compare``
refusal.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

EXIT_REFUSED = 4
ENGINE_NAME = "moonshine-voice"
LANGUAGE = "en"

#: The `moonshine-voice` 0.1.6 `ModelArch` names. ``tiny``/``base`` are the legacy
#: non-streaming architectures (v1 weights, re-exported as `.ort`); the ``*-streaming``
#: arches are Moonshine v2. Comparing v1-in-the-old-package with ``base`` isolates the
#: runtime change from the model change. The enum also has ``base-streaming``, but the
#: 0.1.6 catalog publishes no English model for it, so it is not offered.
ARCHES = ("tiny", "base", "tiny-streaming", "small-streaming", "medium-streaming")
STREAMING_ARCHES = frozenset(a for a in ARCHES if a.endswith("-streaming"))

_RATE = 16000


# ---- pure helpers (tested directly) -------------------------------------------------

def _norm_ws(text: str) -> str:
    return " ".join(text.split())


def count_retractions(texts: list[str]) -> int:
    """How often a line's text changed other than by appending.

    The streaming delivery boundary cares about exactly this: an append-only partial can
    be shown and extended, while a retraction rewrites something the user has already
    seen. Whitespace is normalised so a re-spaced but identical prefix is not a retraction.
    """
    retractions = 0
    previous = ""
    for raw in texts:
        current = _norm_ws(raw)
        if previous and not current.startswith(previous):
            retractions += 1
        previous = current
    return retractions


def partial_stats(events: list[tuple[int, str]]) -> dict:
    """Summarise ``(line_id, text)`` change events from one streamed file."""
    by_line: dict[int, list[str]] = {}
    for line_id, text in events:
        by_line.setdefault(line_id, []).append(text)
    return {
        "lines": len(by_line),
        "text_changes": len(events),
        "retractions": sum(count_retractions(t) for t in by_line.values()),
    }


def sha256_manifest(directory: Path) -> dict:
    """SHA-256 of every regular file under *directory*, plus one digest over the list."""
    files: dict[str, str] = {}
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        files[path.relative_to(directory).as_posix()] = h.hexdigest()
    combined = hashlib.sha256(
        "".join(f"{name}\0{digest}\n" for name, digest in files.items()).encode()).hexdigest()
    return {"root": str(directory), "files": files, "combined_sha256": combined}


def _sample_errors(sample: dict) -> tuple[int, int]:
    errors = sample["substitutions"] + sample["deletions"] + sample["insertions"]
    ref_words = sample["hits"] + sample["substitutions"] + sample["deletions"]
    return errors, ref_words


def paired_bootstrap(a: list[tuple[int, int]], b: list[tuple[int, int]], *,
                     n_resamples: int = 10000, seed: int = 0) -> dict:
    """95 % percentile interval for WER(b) - WER(a), resampling *files* in pairs.

    Files are the resampling unit because the community corpus carries no speaker IDs;
    ADR-033 asks for speaker/group blocks, so a run on a corpus that has them should
    block on them instead, and the JSON records which unit was used.
    """
    if len(a) != len(b) or not a:
        raise ValueError("paired bootstrap needs two equal, non-empty lists")
    ea, ra = np.array([x[0] for x in a]), np.array([x[1] for x in a])
    eb, rb = np.array([x[0] for x in b]), np.array([x[1] for x in b])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), size=(n_resamples, len(a)))
    ref_a, ref_b = ra[idx].sum(axis=1), rb[idx].sum(axis=1)
    ok = (ref_a > 0) & (ref_b > 0)
    deltas = eb[idx].sum(axis=1)[ok] / ref_b[ok] - ea[idx].sum(axis=1)[ok] / ref_a[ok]
    point = eb.sum() / max(1, rb.sum()) - ea.sum() / max(1, ra.sum())
    lo, hi = (np.percentile(deltas, [2.5, 97.5]) if deltas.size else (float("nan"),) * 2)
    return {"delta_wer": float(point), "ci95": [float(lo), float(hi)],
            "n_resamples": n_resamples, "seed": seed, "unit": "file"}


@dataclass
class Refusal:
    problems: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.problems)


def check_comparable(docs: list[dict], *, allow_partial: bool = False) -> Refusal:
    """Everything that would make a paired comparison of these runs meaningless."""
    refusal = Refusal()
    if len(docs) < 2:
        refusal.problems.append("compare needs at least two run files")
        return refusal
    norms = {d["header"].get("normalizer") for d in docs}
    if len(norms) != 1:
        refusal.problems.append(f"runs used different normalisers: {sorted(map(str, norms))}")
    file_sets = [frozenset(s["file"] for s in d["samples"]) for d in docs]
    if len(set(file_sets)) != 1:
        refusal.problems.append("runs scored different file sets; pair them on one corpus")
    for d in docs:
        label = _label(d)
        engine = d["header"].get("engine") or {}
        if engine.get("fallback"):
            refusal.problems.append(f"{label}: the factory fell back; the row is another engine")
        if not engine.get("verified"):
            refusal.problems.append(f"{label}: the resolved engine is unverified")
        cov = d["summary"]["coverage"]
        if cov["n_scored"] != cov["n_total"] and not allow_partial:
            refusal.problems.append(
                f"{label}: coverage {cov['n_scored']}/{cov['n_total']} (pass --allow-partial)")
    return refusal


def _label(doc: dict) -> str:
    engine = doc["header"].get("engine") or {}
    return f"{engine.get('resolved_engine') or doc['header'].get('subject')}:" \
           f"{engine.get('resolved_model') or doc['header'].get('model')}"


def compare(docs: list[dict], *, seed: int = 0, n_resamples: int = 10000) -> dict:
    """The comparison table: the first run is the baseline every other run is paired with."""
    files = sorted(s["file"] for s in docs[0]["samples"])

    def per_file(doc: dict) -> list[tuple[int, int]]:
        by_file = {s["file"]: s for s in doc["samples"]}
        return [_sample_errors(by_file[f]) for f in files]

    base = per_file(docs[0])
    rows = []
    for doc in docs:
        errs = per_file(doc)
        total_err, total_ref = sum(e for e, _ in errs), sum(r for _, r in errs)
        header = doc["header"]
        row: dict[str, Any] = {
            "label": _label(doc),
            "wer": total_err / max(1, total_ref),
            "decode": doc["summary"]["decode"],
            "rtf": doc["summary"]["rtf"],
            "cold_load_s": header.get("cold_load_s"),
            "peak_rss_mb": doc["summary"].get("peak_rss_mb"),
            "weights_sha256": (header.get("weights") or {}).get("combined_sha256"),
            "commit": header.get("commit"),
            "versions": header.get("versions"),
            "streaming": doc.get("streaming", {}).get("summary"),
        }
        if doc is not docs[0]:
            row["vs_baseline"] = paired_bootstrap(base, errs, seed=seed, n_resamples=n_resamples)
        rows.append(row)
    return {"protocol": docs[0]["header"].get("protocol"), "n_files": len(files),
            "normalizer": docs[0]["header"].get("normalizer"), "rows": rows}


def markdown(result: dict) -> str:
    def ms(v: float | None) -> str:
        return "n/a" if v is None else f"{v:.0f}"

    lines = [f"Paired on {result['n_files']} files, normaliser `{result['normalizer']}`.", "",
             "| Run | WER | ΔWER vs first (95 % CI) | decode p50 ms | p95 ms | RTF | "
             "release→final p50 ms | retractions | weights sha256 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for row in result["rows"]:
        vs = row.get("vs_baseline")
        delta = ("baseline" if vs is None else
                 f"{vs['delta_wer'] * 100:+.2f} pp ({vs['ci95'][0] * 100:+.2f}, "
                 f"{vs['ci95'][1] * 100:+.2f})")
        st = row.get("streaming") or {}
        digest = (row["weights_sha256"] or "unrecorded")[:12]
        lines.append(
            f"| `{row['label']}` | {row['wer'] * 100:.2f} % | {delta} | "
            f"{ms(row['decode'].get('p50_ms'))} | {ms(row['decode'].get('p95_ms'))} | "
            f"{row['rtf']:.3f} | {ms(st.get('release_to_final_p50_ms'))} | "
            f"{st.get('retractions', 'n/a')} | `{digest}` |")
    return "\n".join(lines)


# ---- the moonshine-voice engine (imports the package lazily) -------------------------

def _import_moonshine_voice():
    """Seam for tests. Lazy, so `compare`/`digest` and the test suite never need it."""
    import moonshine_voice

    return moonshine_voice


class MoonshineVoiceEngine:
    """Just enough of the `SttEngine` shape for `bench-stt.py` to score it."""

    engine_name = ENGINE_NAME

    def __init__(self, arch: str, model_dir: Path, mv=None) -> None:
        self._mv = mv or _import_moonshine_voice()
        self.model_name = arch
        self.model_dir = model_dir
        self._arch = self._mv.string_to_model_arch(arch)
        self._transcriber = self._mv.Transcriber(model_path=str(model_dir),
                                                 model_arch=self._arch)

    def transcribe(self, audio: np.ndarray, sample_rate: int = _RATE, *_, **__) -> str:
        samples = np.asarray(audio, dtype=np.float32).reshape(-1).tolist()
        transcript = self._transcriber.transcribe_without_streaming(samples, sample_rate)
        return _norm_ws(" ".join(line.text for line in transcript.lines))

    def stream_file(self, audio: np.ndarray, *, chunk_ms: int, update_interval: float,
                    realtime: bool) -> dict:
        """Replay one file through the native stream, as a held key would feed it.

        ``stop()`` stands in for the key release: everything before it is partials, and
        its own duration is the release-to-final time. Fed as fast as the decoder allows
        unless *realtime*, in which case each chunk waits for its wall-clock slot, so the
        release-to-final time also includes any backlog a slow machine builds up.
        """
        events: list[tuple[int, str]] = []
        first_partial_s: float | None = None
        stream = self._transcriber.create_stream(update_interval=update_interval)
        t_start = time.perf_counter()

        def listener(event) -> None:
            nonlocal first_partial_s
            if isinstance(event, self._mv.LineTextChanged):
                if first_partial_s is None:
                    first_partial_s = time.perf_counter() - t_start
                events.append((int(event.line.line_id), str(event.line.text)))

        stream.add_listener(listener)
        stream.start()
        step = max(1, int(_RATE * chunk_ms / 1000))
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        for i, offset in enumerate(range(0, len(samples), step)):
            if realtime:
                slot = t_start + i * chunk_ms / 1000.0
                delay = slot - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
            stream.add_audio(samples[offset:offset + step].tolist(), _RATE)
        t_release = time.perf_counter()
        final = stream.stop()
        release_to_final = time.perf_counter() - t_release
        stream.close()
        text = _norm_ws(" ".join(line.text for line in (final.lines if final else [])))
        return {"final": text, "release_to_final_s": release_to_final,
                "first_partial_s": first_partial_s, **partial_stats(events)}


def _versions_extra(mv) -> dict:
    from importlib import metadata

    found: dict[str, str | None] = {}
    for dist in ("moonshine-voice", "useful-moonshine-onnx", "onnxruntime"):
        try:
            found[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            found[dist] = None
    libs = Path(mv.__file__).resolve().parent
    found["bundled_onnxruntime_files"] = ",".join(sorted(
        p.name for p in [*libs.glob("*onnxruntime*"), *libs.parent.glob(
            "moonshine_voice.libs/*onnxruntime*")])) or None
    return found


def _load_bench_stt():
    path = Path(__file__).with_name("bench-stt.py")
    spec = importlib.util.spec_from_file_location("bench_stt", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bench_stt"] = mod
    spec.loader.exec_module(mod)
    return mod


def _percentile_ms(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    import math

    rank = min(max(math.ceil(round(fraction * len(ordered), 9)), 1), len(ordered))
    return round(ordered[rank - 1] * 1000.0, 1)


# ---- subcommands ---------------------------------------------------------------------

def cmd_run(args) -> int:
    if args.language != LANGUAGE:
        print(f"Error: only {LANGUAGE!r} is measured; non-English moonshine checkpoints "
              "include Moonshine Community License weights that are not cleared.")
        return 1
    if args.streaming and args.arch not in STREAMING_ARCHES:
        print(f"Error: --streaming needs a *-streaming arch, not {args.arch!r}.")
        return 1
    mv = _import_moonshine_voice()
    if args.fetch:
        print(f"Fetching {args.arch!r} ({LANGUAGE}) from the moonshine-voice CDN -- "
              "the one network step of this run, requested by --fetch.")
        model_path, _arch = mv.get_model_for_language(
            LANGUAGE, mv.string_to_model_arch(args.arch))
        model_dir = Path(model_path)
    elif args.model_dir is not None:
        model_dir = args.model_dir
    else:
        print("Error: pass --model-dir (a prepared model) or --fetch (download it now).")
        return 1
    if not model_dir.is_dir():
        print(f"Error: model directory {model_dir} does not exist.")
        return 1

    bench = _load_bench_stt()
    engine = MoonshineVoiceEngine(args.arch, model_dir, mv=mv)
    bench._build_engine = lambda _cfg: engine          # the harness's own seam
    json_out = args.json_out
    argv = [str(args.dataset), "--engine", ENGINE_NAME, "--model", args.arch,
            "--json-out", str(json_out)]
    if args.allow_partial:
        argv.append("--allow-partial")
    code = bench.main(argv)
    if code not in (0, bench.EXIT_PARTIAL) or not json_out.exists():
        return code

    doc = json.loads(json_out.read_text(encoding="utf-8"))
    doc["header"]["versions"].update(_versions_extra(mv))
    doc["header"]["weights"] = sha256_manifest(model_dir)
    doc["header"]["corpus"] = sha256_manifest(args.dataset)
    doc["header"]["language"] = LANGUAGE
    doc["header"]["model_licence"] = "MIT (moonshine-voice LICENSE: English tiny/base and " \
                                     "all streaming models)"
    if args.streaming:
        doc["streaming"] = _run_streaming(bench, engine, args)
    json_out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Provenance (weights, moonshine-voice, bundled ORT) added to {json_out}")
    return code


def _run_streaming(bench, engine: MoonshineVoiceEngine, args) -> dict:
    normalize, _ = bench._build_normalizer()
    rows = []
    for wav in sorted(args.dataset.glob("*.wav")):
        ref_path = wav.with_suffix(".txt")
        if not ref_path.exists():
            continue
        try:
            audio, _sr = bench._load_audio(wav, _RATE)
        except (RuntimeError, FileNotFoundError) as exc:
            rows.append({"file": wav.name, "failed": str(exc)})
            continue
        res = engine.stream_file(audio, chunk_ms=args.chunk_ms,
                                 update_interval=args.update_interval,
                                 realtime=args.pace == "realtime")
        ref, hyp = normalize(ref_path.read_text(encoding="utf-8").strip()), normalize(res["final"])
        rows.append({"file": wav.name, **res, "hyp": hyp, **bench.word_ops(ref, hyp)})
    ok = [r for r in rows if "failed" not in r]
    errs = sum(r["substitutions"] + r["deletions"] + r["insertions"] for r in ok)
    refs = sum(r["hits"] + r["substitutions"] + r["deletions"] for r in ok)
    return {
        "settings": {"chunk_ms": args.chunk_ms, "update_interval_s": args.update_interval,
                     "pace": args.pace},
        "summary": {
            "n": len(ok), "n_failed": len(rows) - len(ok),
            "wer_streamed_final": errs / refs if refs else None,
            "release_to_final_p50_ms": _percentile_ms([r["release_to_final_s"] for r in ok], .5),
            "release_to_final_p95_ms": (_percentile_ms([r["release_to_final_s"] for r in ok], .95)
                                        if len(ok) >= bench.MIN_SAMPLES_FOR_P95 else None),
            "text_changes": sum(r["text_changes"] for r in ok),
            "retractions": sum(r["retractions"] for r in ok),
        },
        "samples": rows,
    }


def cmd_digest(args) -> int:
    if not args.directory.is_dir():
        print(f"Error: {args.directory} is not a directory.")
        return 1
    manifest = sha256_manifest(args.directory)
    if args.into is None:
        print(json.dumps(manifest, indent=2))
        return 0
    doc = json.loads(args.into.read_text(encoding="utf-8"))
    doc["header"][args.field] = manifest
    args.into.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(manifest['files'])} files, combined {manifest['combined_sha256'][:12]} "
          f"-> {args.into}")
    return 0


def cmd_compare(args) -> int:
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in args.runs]
    refusal = check_comparable(docs, allow_partial=args.allow_partial)
    if refusal:
        for problem in refusal.problems:
            print(f"Error: {problem}")
        return EXIT_REFUSED
    result = compare(docs, seed=args.seed, n_resamples=args.resamples)
    print(markdown(result))
    if args.json_out is not None:
        args.json_out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="score one moonshine-voice arch")
    run.add_argument("dataset", type=Path)
    run.add_argument("--arch", choices=ARCHES, required=True)
    run.add_argument("--language", default=LANGUAGE)
    run.add_argument("--model-dir", type=Path, default=None)
    run.add_argument("--fetch", action="store_true",
                     help="download the model from the moonshine-voice CDN (network)")
    run.add_argument("--json-out", type=Path, required=True)
    run.add_argument("--allow-partial", action="store_true")
    run.add_argument("--streaming", action="store_true",
                     help="also replay each file through the native streaming API")
    run.add_argument("--chunk-ms", type=int, default=20)
    run.add_argument("--update-interval", type=float, default=0.5)
    run.add_argument("--pace", choices=("fast", "realtime"), default="fast")
    run.set_defaults(func=cmd_run)

    dig = sub.add_parser("digest", help="SHA-256 manifest of a model directory")
    dig.add_argument("directory", type=Path)
    dig.add_argument("--into", type=Path, default=None, help="run JSON to annotate")
    dig.add_argument("--field", choices=("weights", "corpus"), default="weights",
                     help="which header field the manifest goes into")
    dig.set_defaults(func=cmd_digest)

    cmp_ = sub.add_parser("compare", help="pair run JSONs; the first is the baseline")
    cmp_.add_argument("runs", type=Path, nargs="+")
    cmp_.add_argument("--allow-partial", action="store_true")
    cmp_.add_argument("--seed", type=int, default=0)
    cmp_.add_argument("--resamples", type=int, default=10000)
    cmp_.add_argument("--json-out", type=Path, default=None)
    cmp_.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
