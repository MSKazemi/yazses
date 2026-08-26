"""Does a cluster-centroid merge see the error a fragment test cannot?

ADR-v2-133 closes with an error its own guard is blind to by construction: one speaker
cut into two *people-sized* clusters. `EN2002b` returns 6 labels for 4 speakers with a
smallest of 98 s, so no fragment-duration threshold reaches it. The ADR says detecting it
needs **cluster centroids**, and no centroid exists in any published artifact -- only
durations and DER. This probe extracts them.

Design, and why it is this shape:

* sherpa-onnx clusters *inside* `OfflineSpeakerDiarization` and never exposes a centroid,
  so the embeddings are recomputed here with `SpeakerEmbeddingExtractor` pointed at the
  **same** model file the diarizer used. Same weights, so the geometry is the one the
  clustering actually saw.
* Which clusters are wrongly split is decided by the **reference RTTM**, not by the
  embeddings -- each hypothesis cluster is mapped to the true speaker it overlaps most.
  Two clusters mapping to one speaker is a split, and that judgement is independent of
  the similarity we are trying to evaluate. Using the embeddings to define the answer and
  then scoring the embeddings against it would be circular.
* The question is therefore *separability*: do split pairs sit at higher centroid
  similarity than genuinely-distinct pairs, and is there a cut between them? A rule is
  only worth shipping if one threshold works across meetings, so every pair from every
  meeting goes into one pool.

Not a shipped code path. Driver code lives here, never in `src/yazses/` (ADR-019).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_diarization import read_rttm, _load_wav, _read_manifest, score  # noqa: E402

MIN_TURN_S = 1.0   # ECAPA-style embedders are unreliable below ~1 s (see cocktail filter)
FRAME = 0.01


def _extractor(config):
    import sherpa_onnx
    from yazses.recimport.diarizer import model_dir, _EMB_MODEL
    emb = model_dir(config) / _EMB_MODEL
    cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb), num_threads=4)
    if not cfg.validate():
        raise SystemExit("embedding extractor config invalid")
    return sherpa_onnx.SpeakerEmbeddingExtractor(cfg)


def _embed(ex, audio: np.ndarray, sr: int) -> np.ndarray | None:
    st = ex.create_stream()
    st.accept_waveform(sample_rate=sr, waveform=audio)
    st.input_finished()
    if not ex.is_ready(st):
        return None
    v = np.asarray(ex.compute(st), dtype=np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 0 else None


def _centroids(ex, audio, sr, turns) -> dict[str, np.ndarray]:
    """Mean of the L2-normalized per-turn embeddings, renormalized. Spherical centroid."""
    acc: dict[str, list[np.ndarray]] = {}
    for t in turns:
        if (t[1] - t[0]) < MIN_TURN_S:
            continue
        seg = audio[int(t[0] * sr): int(t[1] * sr)]
        if seg.size < int(MIN_TURN_S * sr):
            continue
        v = _embed(ex, seg, sr)
        if v is not None:
            acc.setdefault(t[2], []).append(v)
    out = {}
    for spk, vs in acc.items():
        m = np.mean(np.stack(vs), axis=0)
        n = np.linalg.norm(m)
        if n > 0:
            out[spk] = m / n
    return out


def _dominant_true_speaker(hyp_turns, ref_turns, label: str) -> tuple[str | None, float]:
    """Which reference speaker does this hypothesis cluster spend most of its time on?"""
    overlap: dict[str, float] = {}
    for hs, he, hl in hyp_turns:
        if hl != label:
            continue
        for rs, re_, rl in ref_turns:
            o = min(he, re_) - max(hs, rs)
            if o > 0:
                overlap[rl] = overlap.get(rl, 0.0) + o
    if not overlap:
        return None, 0.0
    best = max(overlap, key=overlap.get)
    return best, round(overlap[best], 1)


def run(corpus: Path, profile: str = "recimport", shard: str = "") -> dict:
    import yazses.config as _config
    from yazses.recimport.diarizer import SherpaDiarizer
    from bench_diarization import PROFILES

    cfg = getattr(_config, PROFILES[profile])()
    diarizer = SherpaDiarizer(cfg)
    ex = _extractor(cfg)
    manifest = _read_manifest(corpus)

    # Sharding is over *meetings*, which are independent: each is diarized, embedded and
    # scored on its own audio and its own RTTM, and nothing is pooled until the analysis
    # step. So an N-way split is arithmetically identical to one run, just parallel --
    # 9 hours of audio on one core is ~2.25 h and the box has 16.
    todo = manifest["meetings"]
    if shard:
        i, n = (int(x) for x in shard.split("/"))
        todo = [m for k, m in enumerate(todo) if k % n == i]
        print(f"[shard] {i}/{n}: {[m['id'] for m in todo]}", flush=True)

    pairs, meetings = [], []
    for meta in todo:
        mid = meta["id"]
        audio = _load_wav(corpus / f"{mid}.wav")
        ref = read_rttm(corpus / f"{mid}.rttm")
        turns = [(t.start, t.end, t.speaker) for t in diarizer.diarize(audio, 16000)]
        cents = _centroids(ex, audio, 16000, turns)
        labels = sorted(cents)
        mapping = {L: _dominant_true_speaker(turns, ref, L) for L in labels}

        n_pairs = 0
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                a, b = labels[i], labels[j]
                sim = float(np.dot(cents[a], cents[b]))
                same = (mapping[a][0] is not None and mapping[a][0] == mapping[b][0])
                pairs.append({"meeting": mid, "a": a, "b": b,
                              "cosine": round(sim, 4),
                              "same_true_speaker": same,
                              "true_a": mapping[a][0], "true_b": mapping[b][0]})
                n_pairs += 1
        meetings.append({
            "id": mid, "true_speakers": meta["n_speakers"],
            "hyp_clusters": len(labels),
            "over_count": len(labels) - meta["n_speakers"],
            "pairs": n_pairs,
            "splits": sum(1 for p in pairs if p["meeting"] == mid and p["same_true_speaker"]),
        })
        print(f"[centroid] {mid}: {len(labels)} clusters / {meta['n_speakers']} true, "
              f"{meetings[-1]['splits']} split pair(s) of {n_pairs}", flush=True)

    return {"config": {"corpus": corpus.name,
                       "corpus_kind": manifest["ground_truth"],
                       "caveat": manifest["caveat"],
                       "profile": profile,
                       "cluster_threshold": cfg.cluster_threshold,
                       "max_speakers": cfg.max_speakers,
                       "backend": "sherpa-onnx (pyannote segmentation-3.0 + 3D-Speaker ERes2Net)",
                       "embedding_model": "same ERes2Net file the diarizer clusters with",
                       "min_turn_s": MIN_TURN_S,
                       "n_meetings": len(meetings)},
            "meetings": meetings, "pairs": pairs}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--profile", default="recimport")
    ap.add_argument("--shard", default="", help="i/n -- process every n-th meeting")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    from bench_diarization import with_provenance
    out = with_provenance(run(a.corpus, a.profile, a.shard))
    a.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
