"""Compare pyannote/speaker-diarization-3.1 against community-1 on the same fixtures.

The measurement behind the question "should `yazses transcribe --diarize` move from 3.1 to
community-1?". It produces numbers only when a human runs it; nothing in CI downloads or
runs either model. Both pipelines are gated Hugging Face repos: accept their conditions
and download them once with your own account, then run this script **offline** (the
default sets ``HF_HUB_OFFLINE=1`` before anything imports huggingface_hub).

Usage::

    uv sync --extra diarization-pyannote
    hf download pyannote/speaker-diarization-3.1
    hf download pyannote/speaker-diarization-community-1
    uv run python scripts/bench-pyannote-pipelines.py FIXTURES \\
        --evidence-class synthetic --corpus-label my-corpus --json-out n2.json

``FIXTURES`` holds ``<name>.wav`` (any format ``recimport/audio_io.py`` decodes) next to a
``<name>.rttm`` reference. Use synthetic or explicitly consented recordings only.

What is reported, per pipeline and per *view* of its output:

* **DER** and **JER** from ``pyannote.metrics`` (a dependency of ``pyannote.audio``, so
  present wherever the pipelines run), with the collar and overlap handling recorded;
* DER components (miss, false alarm, confusion) so a time-weighted corpus DER can be
  recomputed from the JSON;
* **speaker-count error** (hypothesis speakers minus reference speakers);
* **wall time** of the pipeline call and the real-time factor; cold load time separately.

A pyannote.audio 4.x pipeline returns both ``speaker_diarization`` and
``exclusive_speaker_diarization``. Both views are scored, and the one
``recimport/pyannote_backend.select_annotation`` would ship is marked, so the comparison
is between what each pipeline would actually hand ``align.py``.

Provenance follows the fields of the proposed ADR-033 gate (not accepted; nothing here
depends on it being accepted): YazSes commit, pipeline repo id, resolved snapshot
revision and a SHA-256 over the snapshot's files, every cached ``pyannote/*`` repo the
pipelines may load internally, library versions, CPU, OS, torch threads, the corpus
label, a SHA-256 per fixture, the evidence class and the scoring settings. Diarization
has no text normaliser; the header says so rather than leaving the field out.

Integrity: every fixture is accounted for. A missing reference, an undecodable file or a
failed pipeline call is recorded, and coverage below 100 % exits 3 unless
``--allow-partial`` is given.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SCHEMA = "yazses-bench-pyannote/1"
PROTOCOL_LABEL = "ADR-033 provenance fields (proposed, not accepted)"

#: The only two pipelines this script will load. Literals, not an argument that takes
#: any repo id: a checkpoint id chooses the code that runs (see .github/SECURITY.md and
#: tests/test_dependency_advisories.py), so a benchmark must not widen that either.
CANDIDATES = (
    "pyannote/speaker-diarization-3.1",
    "pyannote/speaker-diarization-community-1",
)

EVIDENCE_CLASSES = ("synthetic", "consented", "public")
AUDIO_SUFFIXES = (".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus")

Turn = tuple[float, float, str]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def parse_rttm(text: str) -> list[Turn]:
    """Return ``(start, end, speaker)`` turns from RTTM text. Pure.

    Only ``SPEAKER`` lines are read; the format is
    ``SPEAKER <file> <chan> <onset> <duration> <NA> <NA> <speaker> <NA> <NA>``.
    A zero or negative duration is dropped; a malformed line raises ``ValueError``
    with its line number, because a silently skipped reference turn becomes a false
    alarm that is charged to the pipeline.
    """
    turns: list[Turn] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] != "SPEAKER":
            continue
        if len(parts) < 8:
            raise ValueError(f"RTTM line {number}: expected at least 8 fields, got {len(parts)}")
        try:
            onset = float(parts[3])
            duration = float(parts[4])
        except ValueError as exc:
            raise ValueError(f"RTTM line {number}: onset/duration not numeric") from exc
        if duration <= 0:
            continue
        turns.append((onset, onset + duration, parts[7]))
    turns.sort(key=lambda t: t[0])
    return turns


def speaker_count(turns: Iterable[Turn]) -> int:
    """Distinct speaker labels in ``turns``. Pure."""
    return len({spk for _, _, spk in turns})


def speaker_count_error(reference: Iterable[Turn], hypothesis: Iterable[Turn]) -> int:
    """Hypothesis speakers minus reference speakers (signed). Pure."""
    return speaker_count(hypothesis) - speaker_count(reference)


def overlapping_speech_seconds(turns: Iterable[Turn]) -> float:
    """Seconds during which two or more turns are active. Pure.

    Recorded per view: an exclusive view must report 0.0, which makes a view that
    claims to be exclusive and is not visible in the JSON.
    """
    events: list[tuple[float, int]] = []
    for start, end, _ in turns:
        if end > start:
            events.append((start, 1))
            events.append((end, -1))
    events.sort(key=lambda e: (e[0], e[1]))
    active = 0
    last = 0.0
    total = 0.0
    for at, delta in events:
        if active >= 2:
            total += at - last
        active += delta
        last = at
    return round(total, 6)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    """One SHA-256 over every file under ``root`` (relative path + content hash). Pure I/O.

    Symlinks are followed, which is what a Hugging Face snapshot directory needs: its
    files are links into ``blobs/``.
    """
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def discover_fixtures(directory: Path) -> list[tuple[str, Path, Path | None]]:
    """``(name, audio, rttm_or_None)`` for every audio file in ``directory``, sorted."""
    found = []
    for audio in sorted(directory.iterdir()):
        if audio.is_file() and audio.suffix.lower() in AUDIO_SUFFIXES:
            rttm = audio.with_suffix(".rttm")
            found.append((audio.stem, audio, rttm if rttm.is_file() else None))
    return found


@dataclass
class ViewScore:
    """One view (exclusive / regular / legacy) of one pipeline on one fixture."""
    view: str
    shipped: bool
    der: float
    jer: float
    miss: float
    false_alarm: float
    confusion: float
    total: float
    speaker_count_error: int
    hyp_speakers: int
    overlap_s: float


@dataclass
class FixtureResult:
    fixture: str
    duration_s: float
    ref_speakers: int
    wall_s: float
    views: list[ViewScore] = field(default_factory=list)


@dataclass
class PipelineRun:
    pipeline: str
    provenance: dict
    load_s: float | None
    results: list[FixtureResult] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    load_error: str | None = None


def summarise(run: PipelineRun, n_fixtures: int) -> list[dict]:
    """Per-view aggregate rows for one pipeline. Pure.

    ``der_mean`` is the mean across recordings; ``der_time_weighted`` sums error time
    over scored reference time (the md-eval / paper convention). Both are reported
    because ``docs/benchmarks.md`` already uses both and they need not agree.
    """
    by_view: dict[str, list[tuple[FixtureResult, ViewScore]]] = {}
    for result in run.results:
        for score in result.views:
            by_view.setdefault(score.view, []).append((result, score))
    rows = []
    for view, pairs in sorted(by_view.items()):
        scores = [s for _, s in pairs]
        total = sum(s.total for s in scores)
        errors = sum(s.miss + s.false_alarm + s.confusion for s in scores)
        audio = sum(r.duration_s for r, _ in pairs)
        wall = sum(r.wall_s for r, _ in pairs)
        rows.append({
            "pipeline": run.pipeline,
            "view": view,
            "shipped": all(s.shipped for s in scores),
            "n_scored": len(pairs),
            "n_total": n_fixtures,
            "der_mean": sum(s.der for s in scores) / len(scores),
            "der_time_weighted": (errors / total) if total > 0 else None,
            "jer_mean": sum(s.jer for s in scores) / len(scores),
            "miss": sum(s.miss for s in scores) / total if total > 0 else None,
            "false_alarm": sum(s.false_alarm for s in scores) / total if total > 0 else None,
            "confusion": sum(s.confusion for s in scores) / total if total > 0 else None,
            "speaker_count_error_mean": sum(s.speaker_count_error for s in scores) / len(scores),
            "speaker_count_abs_error_mean":
                sum(abs(s.speaker_count_error) for s in scores) / len(scores),
            "speaker_count_exact": sum(1 for s in scores if s.speaker_count_error == 0),
            "overlap_s": sum(s.overlap_s for s in scores),
            "wall_s": wall,
            "rtf": (wall / audio) if audio > 0 else None,
            "load_s": run.load_s,
        })
    return rows


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def render_table(rows: list[dict]) -> str:
    """The markdown table. Coverage and the shipped view ride on every row. Pure."""
    lines = [
        "| Pipeline | View | DER (mean) | DER (time-weighted) | JER (mean) | "
        "Spk-count err (mean / exact) | Wall s (RTF) | Coverage |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        view = row["view"] + (" (shipped)" if row["shipped"] else "")
        rtf = "n/a" if row["rtf"] is None else f"{row['rtf']:.3f}"
        lines.append(
            f"| `{row['pipeline']}` | {view} | {_pct(row['der_mean'])} | "
            f"{_pct(row['der_time_weighted'])} | {_pct(row['jer_mean'])} | "
            f"{row['speaker_count_error_mean']:+.2f} / {row['speaker_count_exact']}"
            f"/{row['n_scored']} | {row['wall_s']:.1f} ({rtf}) | "
            f"{row['n_scored']}/{row['n_total']} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The measurement loop (backends injected, so it is testable without a model)
# ---------------------------------------------------------------------------

#: ``score(reference, hypothesis, duration_s) -> {"der", "jer", "miss", "false_alarm",
#: "confusion", "total"}``.
Scorer = Callable[[list[Turn], list[Turn], float], dict]


def score_views(output, reference: list[Turn], duration_s: float, score: Scorer) -> list[ViewScore]:
    """Score every view the pipeline output offers; mark the one the product reads."""
    from yazses.recimport.pyannote_backend import (
        annotation_to_turns,
        select_annotation,
    )

    _, shipped_kind = select_annotation(output)
    views: dict[str, object] = {}
    for kind, attr in (("exclusive", "exclusive_speaker_diarization"),
                       ("regular", "speaker_diarization")):
        candidate = getattr(output, attr, None)
        if candidate is not None and hasattr(candidate, "itertracks"):
            views[kind] = candidate
    if not views:
        views["legacy"] = output

    out = []
    for kind, annotation in views.items():
        hyp = [(t.start, t.end, t.speaker) for t in annotation_to_turns(annotation, source=output)]
        metrics = score(reference, hyp, duration_s)
        out.append(ViewScore(
            view=kind,
            shipped=(kind == shipped_kind),
            der=float(metrics["der"]),
            jer=float(metrics["jer"]),
            miss=float(metrics["miss"]),
            false_alarm=float(metrics["false_alarm"]),
            confusion=float(metrics["confusion"]),
            total=float(metrics["total"]),
            speaker_count_error=speaker_count_error(reference, hyp),
            hyp_speakers=speaker_count(hyp),
            overlap_s=overlapping_speech_seconds(hyp),
        ))
    return out


def run_pipeline(
    pipeline_id: str,
    fixtures: list[tuple[str, Path, Path | None]],
    *,
    load_pipeline: Callable[[str], Callable],
    load_audio: Callable[[Path], tuple[object, int]],
    score: Scorer,
    provenance: Callable[[str], dict],
    clock: Callable[[], float] = time.perf_counter,
) -> PipelineRun:
    """Load one pipeline, run it on every fixture, and account for every fixture."""
    t0 = clock()
    try:
        apply = load_pipeline(pipeline_id)
    except Exception as exc:  # a gated/missing model is a result, not a crash
        return PipelineRun(pipeline_id, provenance(pipeline_id), None,
                           load_error=f"{type(exc).__name__}: {exc}",
                           failures=[{"fixture": n, "reason": "pipeline did not load"}
                                     for n, _, _ in fixtures])
    run = PipelineRun(pipeline_id, provenance(pipeline_id), clock() - t0)

    for name, audio_path, rttm_path in fixtures:
        if rttm_path is None:
            run.failures.append({"fixture": name, "reason": "no reference .rttm"})
            continue
        try:
            reference = parse_rttm(rttm_path.read_text(encoding="utf-8"))
            audio, sample_rate = load_audio(audio_path)
        except Exception as exc:
            run.failures.append({"fixture": name, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        duration = len(audio) / float(sample_rate)  # type: ignore[arg-type]
        try:
            t1 = clock()
            output = apply(audio, sample_rate)
            wall = clock() - t1
            views = score_views(output, reference, duration, score)
        except Exception as exc:
            run.failures.append({"fixture": name, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        run.results.append(FixtureResult(name, duration, speaker_count(reference), wall, views))
    return run


# ---------------------------------------------------------------------------
# Real backends (lazy: torch / pyannote / huggingface_hub only when actually run)
# ---------------------------------------------------------------------------

def _real_loader(*, allow_download: bool) -> Callable[[str], Callable]:
    def load(pipeline_id: str) -> Callable:
        if pipeline_id not in CANDIDATES:
            raise ValueError(f"{pipeline_id} is not one of {CANDIDATES}")
        from yazses.recimport.pyannote_backend import (
            _auth_token,
            _disable_upstream_telemetry,
        )
        _disable_upstream_telemetry()  # before the import, as the adapter does
        import numpy as np
        import torch
        from pyannote.audio import Pipeline

        # Offline: no token is read at all; the cached snapshot is enough.
        token = _auth_token() if allow_download else None
        pipeline = Pipeline.from_pretrained(pipeline_id, token=token)
        if pipeline is None:
            raise RuntimeError(f"{pipeline_id} did not load (gated, or not in the cache)")
        pipeline = pipeline.to(torch.device("cpu"))

        def apply(audio, sample_rate: int):
            # Same call shape as PyannoteDiarizer.diarize, speaker count left to auto.
            buf = np.asarray(audio, dtype="float32").reshape(1, -1)
            with torch.no_grad():
                return pipeline({"waveform": torch.from_numpy(buf),
                                 "sample_rate": int(sample_rate)})

        return apply

    return load


def _real_audio(path: Path) -> tuple[object, int]:
    from yazses.recimport.audio_io import load_audio

    return load_audio(path, 16000)


def _real_scorer(*, collar: float, skip_overlap: bool) -> Scorer:
    def score(reference: list[Turn], hypothesis: list[Turn], duration_s: float) -> dict:
        from pyannote.core import Annotation, Segment, Timeline
        from pyannote.metrics.diarization import (
            DiarizationErrorRate,
            JaccardErrorRate,
        )

        def to_annotation(turns: list[Turn]) -> Annotation:
            ann = Annotation()
            for i, (start, end, spk) in enumerate(turns):
                ann[Segment(start, end), i] = spk
            return ann

        ref, hyp = to_annotation(reference), to_annotation(hypothesis)
        uem = Timeline([Segment(0.0, max(duration_s, max((e for _, e, _ in reference),
                                                         default=0.0)))])
        detail = DiarizationErrorRate(collar=collar, skip_overlap=skip_overlap)(
            ref, hyp, uem=uem, detailed=True)
        jer = JaccardErrorRate(collar=collar, skip_overlap=skip_overlap)(ref, hyp, uem=uem)
        return {
            "der": detail["diarization error rate"],
            "jer": jer,
            "miss": detail["missed detection"],
            "false_alarm": detail["false alarm"],
            "confusion": detail["confusion"],
            "total": detail["total"],
        }

    return score


def _snapshot_provenance(pipeline_id: str) -> dict:
    """Resolved revision and content hash of the cached snapshot. Local only."""
    try:
        from huggingface_hub import snapshot_download

        path = Path(snapshot_download(pipeline_id, local_files_only=True))
    except Exception as exc:
        return {"repo": pipeline_id, "revision": None, "sha256": None,
                "error": f"{type(exc).__name__}: {exc}"}
    return {"repo": pipeline_id, "revision": path.name, "sha256": sha256_tree(path)}


def _cached_pyannote_repos() -> list[dict]:
    """Every ``pyannote/*`` model in the local HF cache, with its revisions. Local only.

    3.1 loads ``pyannote/segmentation-3.0`` and an embedding repo internally; their
    revisions belong in the record even though this script never names them.
    """
    try:
        from huggingface_hub import scan_cache_dir

        info = scan_cache_dir()
    except Exception as exc:
        return [{"error": f"{type(exc).__name__}: {exc}"}]
    repos = []
    for repo in sorted(info.repos, key=lambda r: r.repo_id):
        if repo.repo_type == "model" and repo.repo_id.startswith("pyannote/"):
            repos.append({"repo": repo.repo_id,
                          "revisions": sorted(r.commit_hash for r in repo.revisions)})
    return repos


def _versions() -> dict:
    from importlib import metadata

    found: dict[str, str | None] = {"python": platform.python_version()}
    for dist in ("yazses", "pyannote.audio", "pyannote.core", "pyannote.metrics",
                 "torch", "torchaudio", "huggingface-hub", "numpy", "av"):
        try:
            found[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            found[dist] = None
    return found


def _git_commit() -> str | None:
    import subprocess

    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def _torch_threads() -> int | None:
    try:
        import torch

        return int(torch.get_num_threads())
    except Exception:
        return None


def run_header(*, corpus_label: str, evidence_class: str, offline: bool,
               collar: float, skip_overlap: bool,
               fixtures: list[tuple[str, Path, Path | None]]) -> dict:
    return {
        "schema": SCHEMA,
        "protocol": PROTOCOL_LABEL,
        "commit": _git_commit(),
        "corpus": {
            "label": corpus_label,
            "evidence_class": evidence_class,
            "fixtures": [
                {"name": name, "audio_sha256": sha256_file(audio),
                 "rttm_sha256": sha256_file(rttm) if rttm else None}
                for name, audio, rttm in fixtures
            ],
        },
        "normalizer": "n/a (diarization is not scored on text)",
        "scoring": {"tool": "pyannote.metrics", "collar_s": collar,
                    "skip_overlap": skip_overlap, "uem": "whole file",
                    "speaker_count": "auto (no min/max/num_speakers passed)"},
        "offline": offline,
        "versions": _versions(),
        "cached_pyannote_repos": _cached_pyannote_repos(),
        "cpu": {"machine": platform.machine(), "processor": platform.processor() or None,
                "logical_cores": os.cpu_count(), "torch_threads": _torch_threads()},
        "os": platform.platform(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("fixtures", type=Path, help="directory of <name>.wav + <name>.rttm")
    parser.add_argument("--pipelines", nargs="+", choices=CANDIDATES, default=list(CANDIDATES))
    parser.add_argument("--evidence-class", required=True, choices=EVIDENCE_CLASSES,
                        help="what the fixtures are; never real users' recordings without consent")
    parser.add_argument("--corpus-label", required=True)
    parser.add_argument("--collar", type=float, default=0.0,
                        help="pyannote.metrics collar in seconds (total width; default 0)")
    parser.add_argument("--skip-overlap", action="store_true")
    parser.add_argument("--allow-download", action="store_true",
                        help="permit a Hugging Face fetch (default: HF_HUB_OFFLINE=1)")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)

    offline = not args.allow_download
    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"  # before anything imports huggingface_hub

    if not args.fixtures.is_dir():
        print(f"error: {args.fixtures} is not a directory", file=sys.stderr)
        return 2
    fixtures = discover_fixtures(args.fixtures)
    if not fixtures:
        print(f"error: no audio files in {args.fixtures}", file=sys.stderr)
        return 2

    header = run_header(corpus_label=args.corpus_label, evidence_class=args.evidence_class,
                        offline=offline, collar=args.collar, skip_overlap=args.skip_overlap,
                        fixtures=fixtures)
    loader = _real_loader(allow_download=args.allow_download)
    scorer = _real_scorer(collar=args.collar, skip_overlap=args.skip_overlap)

    runs = [run_pipeline(pid, fixtures, load_pipeline=loader, load_audio=_real_audio,
                         score=scorer, provenance=_snapshot_provenance)
            for pid in args.pipelines]
    rows = [row for run in runs for row in summarise(run, len(fixtures))]

    print(render_table(rows))
    complete = True
    for run in runs:
        if run.load_error:
            print(f"\n{run.pipeline}: did not load -- {run.load_error}", file=sys.stderr)
        for failure in run.failures:
            complete = False
            print(f"{run.pipeline}: {failure['fixture']}: {failure['reason']}", file=sys.stderr)

    if args.json_out:
        payload = {
            "header": header,
            "summary": rows,
            "runs": [{
                "pipeline": run.pipeline,
                "provenance": run.provenance,
                "load_s": run.load_s,
                "load_error": run.load_error,
                "failures": run.failures,
                "fixtures": [{
                    "fixture": r.fixture, "duration_s": r.duration_s,
                    "ref_speakers": r.ref_speakers, "wall_s": r.wall_s,
                    "views": [vars(v) for v in r.views],
                } for r in run.results],
            } for run in runs],
        }
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if not complete and not args.allow_partial:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
