"""Turn a downloaded diarization dataset into the corpus layout `bench_diarization` reads.

`bench_diarization.py` scores whatever it is handed, provided the directory holds
`<id>.wav`, `<id>.rttm` and a `manifest.json` declaring where the reference came from.
`scripts/gen-meeting-corpus.py` produces one such corpus by synthesis; this produces
others from public annotated datasets.

Why bother, given a corpus already exists: the synthetic one establishes that
`[recimport] cluster_threshold = 0.5` is dominated, but it cannot establish *what to
set instead*. Neural TTS voices sit further apart in embedding space than people in a
room, and a clustering threshold is precisely the parameter that over-fits to that
gap. Real recordings are what turn a direction into a defensible default.

Two sources are supported and they answer different questions:

- **ami** -- the AMI Meeting Corpus headset mix. Four-person meetings in real rooms:
  the actual thing Meeting Mode is pointed at, and therefore the number that can
  justify changing a shipped default.
- **voxconverse** -- broadcast and YouTube audio. Harder acoustically and easier in
  turn structure than a meeting, so it is a generalisation check rather than a
  target-domain measurement.

**No network access here.** Following `_common.py`'s LibriSpeech precedent, the
download is a documented command in `README.md` and this file only rearranges what is
already on disk, so the benchmark tree stays inspectable and offline-reproducible.

## Subset selection

Scoring every recording costs hours of audio per threshold and a sweep is six of
those, so a subset is taken -- and *how* is load-bearing:

- **Equal count from every bucket**, where the bucket is the axis the dataset varies
  along: reference speaker count for VoxConverse, recording session for AMI (whose
  meetings are all four-person, so speaker count would put everything in one bucket
  and then take four parts of one session before touching another room). Speaker
  count is the failure this exercise is about -- the synthetic run over-estimated it
  in 8 of 8 -- so a subset that under-samples crowded recordings would measure the
  diarizer on the cases it already handles.

  Equal *count* rather than equal *time*, because `bench_diarization.run()` averages
  DER across meetings without weighting by duration. A bucket's influence on the
  published number is how many recordings it contributed, so that is what has to be
  equalised.
- **Deterministic**: buckets in sorted order, files sorted by id within a bucket, no
  RNG. The same tree yields the same subset on any machine.
- **Not ordered by duration.** The obvious way to fit a budget is to take the
  shortest files, and it is a trap twice over: short recordings tend to have fewer
  speakers *and* give clustering less evidence to work with, so it would move the
  measurement in an unknown direction while looking like mere thrift. The subtler
  form of the same trap is a round-robin that *skips* an over-budget file instead of
  stopping -- the bucket with the shortest files then keeps taking turns after the
  others are shut out, which a smoke test caught doing exactly that.

The chosen ids go into the manifest, so a published number names the exact recordings
behind it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import wave
from collections import defaultdict
from pathlib import Path

SAMPLE_RATE = 16000


def _bucket_by_speaker_count(fid: str, speakers: set[str]) -> str:
    return f"{len(speakers):02d}-speakers"


def _bucket_by_ami_session(fid: str, speakers: set[str]) -> str:
    # "ES2004a" -> "ES2004": the four parts of one session share a room and a cast,
    # so they are near-duplicates for this measurement and belong in one bucket.
    return fid[:-1] if fid and fid[-1].isalpha() else fid


# `ground_truth` and `caveat` are copied verbatim into the result JSON and published
# beside the number, so they say plainly how far each figure travels.
SOURCES = {
    "ami": {
        "source": "AMI Meeting Corpus, headset mix, official test split",
        "source_url": "https://groups.inf.ed.ac.uk/ami/corpus/",
        "citation": "Carletta et al., MLMI 2005; RTTM from pyannote/AMI-diarization-setup",
        "ground_truth": (
            "human-annotated RTTM from pyannote/AMI-diarization-setup (only_words, "
            "test split) over the AMI headset mix"
        ),
        "caveat": (
            "real four-person meetings in real rooms: a genuine DER for Meeting Mode's "
            "target domain, not a floor. Headset mix is cleaner than a single "
            "table microphone, so a far-field recording scores worse. Not comparable "
            "with the synthetic-corpus figure; the two are different measurements."
        ),
        "bucket": _bucket_by_ami_session,
    },
    "voxconverse": {
        "source": "VoxConverse dev",
        "source_url": "https://github.com/joonson/voxconverse",
        "citation": "Chung, Huh, Nagrani, Afouras, Zisserman. Interspeech 2020",
        "ground_truth": (
            "human-annotated RTTM from the VoxConverse dev release "
            "(https://github.com/joonson/voxconverse)"
        ),
        "caveat": (
            "real recordings, human annotation: a genuine DER, not a floor -- but "
            "VoxConverse is broadcast and YouTube audio, so it is harder than Meeting "
            "Mode's target in acoustics and easier in turn structure. A generalisation "
            "check, not a target-domain number. Not comparable with the "
            "synthetic-corpus figure; the two are different measurements."
        ),
        "bucket": _bucket_by_speaker_count,
    },
}


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _speakers(rttm: Path) -> set[str]:
    out = set()
    for line in rttm.read_text(encoding="utf-8").splitlines():
        p = line.split()
        if len(p) >= 8 and p[0] == "SPEAKER":
            out.add(p[7])
    return out


def _normalise(src: Path, dst: Path) -> None:
    """Write *src* to *dst* as 16 kHz mono 16-bit PCM.

    `bench_diarization._load_wav` asserts that shape rather than converting, which is
    right for a scorer -- a resample is a measurement decision and belongs in corpus
    preparation, where the manifest records it. Conforming files are copied so the
    bytes stay identical.
    """
    with wave.open(str(src), "rb") as w:
        conforming = (
            w.getframerate() == SAMPLE_RATE
            and w.getnchannels() == 1
            and w.getsampwidth() == 2
        )
    if conforming:
        shutil.copyfile(src, dst)
        return
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16", str(dst)],
        check=True,
    )


def build(source: str, wav_dir: Path, rttm_dir: Path, out: Path,
          budget_minutes: float) -> dict:
    if source not in SOURCES:
        raise SystemExit(f"unknown source {source!r}; valid: {sorted(SOURCES)}")
    spec = SOURCES[source]

    wavs = {p.stem: p for p in wav_dir.rglob("*.wav")}
    rttms = {p.stem: p for p in rttm_dir.rglob("*.rttm")}
    ids = sorted(set(wavs) & set(rttms))
    if not ids:
        raise SystemExit(
            f"no id has both a .wav under {wav_dir} and a .rttm under {rttm_dir}. "
            f"wav stems: {sorted(wavs)[:4]}; rttm stems: {sorted(rttms)[:4]}"
        )

    speakers = {fid: _speakers(rttms[fid]) for fid in ids}
    buckets: dict[str, list[str]] = defaultdict(list)
    for fid in ids:
        buckets[spec["bucket"](fid, speakers[fid])].append(fid)

    order = sorted(buckets)
    budget_s = budget_minutes * 60.0

    def _take(depth: int) -> list[str]:
        """The first *depth* ids of every bucket, in id order."""
        return [fid for b in order for fid in buckets[b][:depth]]

    def _seconds(fids: list[str]) -> float:
        return sum(_wav_seconds(wavs[f]) for f in fids)

    # Take the same NUMBER of recordings from every bucket -- the largest depth that
    # fits the budget, and never fewer than one.
    #
    # The obvious alternative, walking buckets round-robin and skipping any file that
    # would bust the budget, is silently biased: the skip lets whichever bucket holds
    # the shortest files keep contributing after the others have been shut out. A
    # smoke test on evenly-structured input had one AMI session supply three of six
    # recordings for exactly that reason. Equal time per bucket has the same defect
    # in reverse, because `run()` averages DER across meetings rather than weighting
    # by duration -- so a bucket's influence is its file count, and file count is
    # what has to be equalised.
    depth = 1
    while depth < max(len(buckets[b]) for b in order) and _seconds(_take(depth + 1)) <= budget_s:
        depth += 1
    chosen = _take(depth)

    out.mkdir(parents=True, exist_ok=True)
    meetings = []
    for fid in sorted(chosen):
        _normalise(wavs[fid], out / f"{fid}.wav")
        shutil.copyfile(rttms[fid], out / f"{fid}.rttm")
        meetings.append({
            "id": fid,
            "duration_s": round(_wav_seconds(out / f"{fid}.wav"), 2),
            "n_speakers": len(speakers[fid]),
        })
        print(f"[{source}] {fid}: {meetings[-1]['duration_s']}s, "
              f"{meetings[-1]['n_speakers']} speakers", flush=True)

    manifest = {
        "generator": "paper/benchmark/make_corpus.py",
        "source": spec["source"],
        "source_url": spec["source_url"],
        "citation": spec["citation"],
        "sample_rate": SAMPLE_RATE,
        "ground_truth": spec["ground_truth"],
        "caveat": spec["caveat"],
        "selection": (
            f"the first {depth} recording(s), in id order, from each of {len(order)} "
            f"buckets ({spec['bucket'].__name__.removeprefix('_bucket_by_')}); depth "
            f"is the largest that fits {budget_minutes:g} minutes, minimum 1, so the "
            f"budget is exceeded when one recording per bucket already exceeds it. "
            f"Equal count per bucket, never ordered by duration"
        ),
        "n_available": len(ids),
        "bucket_sizes": {b: len(v) for b, v in sorted(buckets.items())},
        "total_audio_seconds": round(sum(m["duration_s"] for m in meetings), 1),
        "meetings": meetings,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n{len(meetings)} of {len(ids)} recordings, "
          f"{manifest['total_audio_seconds'] / 60:.1f} min -> {out}")
    return manifest


if __name__ == "__main__":
    if len(sys.argv) < 5:
        raise SystemExit(
            f"usage: make_corpus.py <{'|'.join(sorted(SOURCES))}> <wav_dir> <rttm_dir> "
            "<out_dir> [budget_minutes]"
        )
    build(
        sys.argv[1],
        Path(sys.argv[2]),
        Path(sys.argv[3]),
        Path(sys.argv[4]),
        float(sys.argv[5]) if len(sys.argv) > 5 else 90.0,
    )
