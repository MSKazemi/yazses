"""Diarization error rate for Meeting Mode's speaker separation.

`docs/benchmarks.md` says speaker separation is not measured. This measures it.

Scores any corpus laid out as `<id>.wav` + `<id>.rttm` + `manifest.json`. Two exist:

- the synthetic corpus from `scripts/gen-meeting-corpus.py`, whose ground truth is
  exact rather than annotated -- the renderer placed every turn, so the reference is
  the instruction the mixer was given, not somebody's estimate of it;
- VoxConverse dev, via `make_corpus_voxconverse.py` -- real recordings, human
  annotation.

**The two numbers are different measurements and must never be averaged or
compared.** The synthetic figure is a regression floor: neural TTS voices are cleaner
and further apart in embedding space than people in a room, so a diarizer scores
optimistically, and what the figure is good for is noticing that a change made it
worse. The VoxConverse figure is a real DER, and it is the one that can justify
changing a default. Each corpus states which it is in its own manifest, and
`_read_manifest` refuses a corpus that does not say.

Because the synthetic reference has no annotation error, the usual reason a collar
is required does not apply to it, so DER at **collar 0** is the primary number, with
the NIST 250 ms collar reported alongside only so the figure can be set next to
published ones. On an annotated corpus the collared number is the comparable one.

Scoring is frame-based (10 ms) with an optimal one-to-one speaker mapping via the
Hungarian algorithm, which is what NIST md-eval does. Reimplemented rather than
pulled in: `pyannote.metrics` would add pyannote.audio to the benchmark group, and
the point of the sherpa backend is that Meeting Mode needs no torch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

FRAME = 0.010  # seconds; md-eval's default resolution


def read_rttm(path: Path) -> list[tuple[float, float, str]]:
    """(start, end, speaker) from a NIST RTTM file."""
    turns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 8 and parts[0] == "SPEAKER":
            start, dur = float(parts[3]), float(parts[4])
            turns.append((start, start + dur, parts[7]))
    return turns


def _label_frames(turns, n_frames: int, speakers: list[str]) -> np.ndarray:
    """Boolean [speaker, frame] occupancy. Overlap is represented, not collapsed."""
    idx = {s: i for i, s in enumerate(speakers)}
    grid = np.zeros((len(speakers), n_frames), dtype=bool)
    for start, end, spk in turns:
        a = max(0, int(round(start / FRAME)))
        b = min(n_frames, int(round(end / FRAME)))
        if b > a:
            grid[idx[spk], a:b] = True
    return grid


def _collar_mask(turns, n_frames: int, collar: float) -> np.ndarray:
    """Frames to score. A collar forgives `collar` seconds either side of a boundary."""
    keep = np.ones(n_frames, dtype=bool)
    if collar <= 0:
        return keep
    half = int(round(collar / FRAME))
    for start, end in [(t[0], t[1]) for t in turns]:
        for boundary in (start, end):
            c = int(round(boundary / FRAME))
            keep[max(0, c - half):min(n_frames, c + half + 1)] = False
    return keep


def score(ref_turns, hyp_turns, collar: float = 0.0) -> dict:
    """Frame-based DER with an optimal one-to-one reference<->hypothesis mapping."""
    from scipy.optimize import linear_sum_assignment

    end = max([t[1] for t in ref_turns + hyp_turns] or [0.0])
    n = int(np.ceil(end / FRAME)) + 1
    ref_spk = sorted({t[2] for t in ref_turns})
    hyp_spk = sorted({t[2] for t in hyp_turns})
    ref = _label_frames(ref_turns, n, ref_spk)
    hyp = _label_frames(hyp_turns, n, hyp_spk)

    keep = _collar_mask(ref_turns, n, collar)
    ref, hyp = ref[:, keep], hyp[:, keep]

    # Hungarian on the overlap matrix: maximise agreement, so minimise -overlap.
    if ref_spk and hyp_spk:
        overlap = (ref.astype(np.int64) @ hyp.astype(np.int64).T)
        rows, cols = linear_sum_assignment(-overlap)
        correct = int(overlap[rows, cols].sum())
    else:
        correct = 0

    n_ref = ref.sum(axis=0)            # reference speakers active per frame
    n_hyp = hyp.sum(axis=0)
    total = int(n_ref.sum())           # total reference speaker-time, md-eval's denominator
    missed = int(np.maximum(n_ref - n_hyp, 0).sum())
    false_alarm = int(np.maximum(n_hyp - n_ref, 0).sum())
    # Confusion is the mapped-speaker time that agrees with neither: whatever is
    # scored as speech in both but not matched by the optimal assignment.
    confusion = int(np.minimum(n_ref, n_hyp).sum()) - correct
    confusion = max(0, confusion)

    der = (missed + false_alarm + confusion) / total if total else 0.0
    return {
        "der": round(der * 100, 2),
        "missed_pct": round(missed / total * 100, 2) if total else 0.0,
        "false_alarm_pct": round(false_alarm / total * 100, 2) if total else 0.0,
        "confusion_pct": round(confusion / total * 100, 2) if total else 0.0,
        "n_ref_speakers": len(ref_spk),
        "n_hyp_speakers": len(hyp_spk),
        "speaker_count_error": len(hyp_spk) - len(ref_spk),
        "scored_seconds": round(total * FRAME, 1),
        "collar_s": collar,
    }


def _load_wav(path: Path) -> np.ndarray:
    import wave

    with wave.open(str(path), "rb") as w:
        assert w.getsampwidth() == 2 and w.getnchannels() == 1
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def _read_manifest(corpus: Path) -> dict:
    """Load *corpus*/manifest.json, refusing one that does not declare its provenance.

    `ground_truth` and `caveat` are copied verbatim into the result JSON, and they
    are what tell a reader how far the number travels. They used to be literals in
    the config block, which was harmless for exactly as long as one corpus existed:
    the wording read "synthetic (Azure neural TTS); ground truth exact by
    construction", so pointing this bench at VoxConverse or AMI would have published
    a real-room DER under the synthetic label -- and the synthetic label is
    precisely the thing that marks the number as a floor.

    A corpus that does not declare them is refused rather than defaulted, because
    the only available default is a sentence describing some other corpus.
    """
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    missing = [k for k in ("ground_truth", "caveat") if not manifest.get(k)]
    if missing:
        raise SystemExit(
            f"{corpus / 'manifest.json'} does not declare {', '.join(missing)}. "
            "Every corpus must say how its reference was produced and how far the "
            "resulting DER generalises; those strings are published with the number."
        )
    return manifest


def write_rttm(path: Path, file_id: str, turns) -> None:
    """Write *turns* as a NIST RTTM, so a standard scorer can check this one.

    `score()` is a reimplementation -- frame-based DER with a Hungarian one-to-one
    mapping, matching md-eval's semantics -- chosen over pulling in
    `pyannote.metrics`, which would add pyannote.audio to the benchmark group and
    undo the point of a sherpa backend that needs no torch. The cost of that choice
    is that a bug in the scorer would be invisible: every number here would move
    together and nothing would look wrong.

    Dumping the hypothesis in the standard format removes that. The same files can
    be handed to `md-eval.pl` or `dscore` and the DER compared, so the scorer is
    checkable by something that was not written here.
    """
    lines = [
        f"SPEAKER {file_id} 1 {start:.3f} {end - start:.3f} <NA> <NA> {spk} <NA> <NA>"
        for start, end, spk in turns
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(corpus: Path, max_speakers: int = 0, dump_rttm: Path | None = None) -> dict:
    """Diarize every meeting in *corpus* and score it against its own RTTM."""
    from yazses.config import RecimportConfig
    from yazses.recimport.diarizer import SherpaDiarizer

    manifest = _read_manifest(corpus)
    cfg = RecimportConfig()
    # max_speakers=0 leaves sherpa's clustering to decide the count, which is the
    # honest setting: Meeting Mode does not know how many people are in the room.
    diarizer = SherpaDiarizer(
        type(cfg)(**{**cfg.__dict__, "max_speakers": max_speakers})
        if max_speakers else cfg
    )

    per_meeting = []
    for meta in manifest["meetings"]:
        mid = meta["id"]
        audio = _load_wav(corpus / f"{mid}.wav")
        ref = read_rttm(corpus / f"{mid}.rttm")
        turns = diarizer.diarize(audio, 16000)
        hyp = [(t.start, t.end, t.speaker) for t in turns]
        if dump_rttm is not None:
            dump_rttm.mkdir(parents=True, exist_ok=True)
            write_rttm(dump_rttm / f"{mid}.rttm", mid, hyp)
        row = {"id": mid, "duration_s": meta["duration_s"],
               "true_speakers": meta["n_speakers"]}
        for collar in (0.0, 0.25):
            key = "strict" if collar == 0.0 else "collar250ms"
            row[key] = score(ref, hyp, collar)
        per_meeting.append(row)
        print(f"[der] {mid}: DER={row['strict']['der']}% "
              f"(collar250={row['collar250ms']['der']}%) "
              f"speakers {row['strict']['n_hyp_speakers']}/{row['true_speakers']}",
              flush=True)

    def _mean(key: str, field: str) -> float:
        vals = [m[key][field] for m in per_meeting]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    return {
        "config": {
            "corpus": str(corpus),
            "corpus_kind": manifest["ground_truth"],
            "caveat": manifest["caveat"],
            "backend": "sherpa-onnx (pyannote segmentation-3.0 + 3D-Speaker ERes2Net)",
            "frame_s": FRAME,
            "scoring": "frame-based, Hungarian one-to-one mapping (md-eval semantics)",
            "n_meetings": len(per_meeting),
        },
        "summary": {
            "der_strict": _mean("strict", "der"),
            "der_collar250ms": _mean("collar250ms", "der"),
            "missed_pct": _mean("strict", "missed_pct"),
            "false_alarm_pct": _mean("strict", "false_alarm_pct"),
            "confusion_pct": _mean("strict", "confusion_pct"),
            "mean_speaker_count_error": _mean("strict", "speaker_count_error"),
        },
        "meetings": per_meeting,
    }


def sweep(corpus: Path, thresholds=(0.4, 0.5, 0.6, 0.7, 0.8, 0.9)) -> list[dict]:
    """Score the corpus at several `[recimport] cluster_threshold` values.

    Kept in the harness rather than in a throwaway script because the first run of
    this bench found the shipped default sitting well off the optimum, and a claim
    like that has to stay re-runnable by anyone who doubts it.
    """
    from dataclasses import replace

    from yazses.config import RecimportConfig
    from yazses.recimport.diarizer import SherpaDiarizer

    manifest = _read_manifest(corpus)
    rows = []
    for thr in thresholds:
        diar = SherpaDiarizer(replace(RecimportConfig(), cluster_threshold=thr))
        ders, errs = [], []
        for meta in manifest["meetings"]:
            mid = meta["id"]
            hyp = [(t.start, t.end, t.speaker)
                   for t in diar.diarize(_load_wav(corpus / f"{mid}.wav"), 16000)]
            got = score(read_rttm(corpus / f"{mid}.rttm"), hyp, 0.0)
            ders.append(got["der"])
            errs.append(got["speaker_count_error"])
        rows.append({
            "cluster_threshold": thr,
            "der": round(sum(ders) / len(ders), 2),
            "mean_speaker_count_error": round(sum(errs) / len(errs), 2),
            "meetings_with_exact_count": sum(1 for e in errs if e == 0),
            "n_meetings": len(errs),
        })
        print(f"[sweep] threshold={thr}  DER={rows[-1]['der']}%  "
              f"count_err={rows[-1]['mean_speaker_count_error']:+.2f}  "
              f"exact={rows[-1]['meetings_with_exact_count']}/{len(errs)}", flush=True)
    return rows


if __name__ == "__main__":
    argv = sys.argv[1:]
    dump_dir = None
    if "--dump-rttm" in argv:
        i = argv.index("--dump-rttm")
        dump_dir = Path(argv[i + 1])
        del argv[i:i + 2]
    args = [a for a in argv if a != "--sweep"]
    corpus_dir = Path(args[0])
    if "--sweep" in sys.argv:
        out = {"sweep": sweep(corpus_dir)}
    else:
        out = run(corpus_dir, dump_rttm=dump_dir)
        print(json.dumps(out["summary"], indent=2))
    if len(args) > 1:
        Path(args[1]).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
