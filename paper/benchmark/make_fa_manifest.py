"""Build a Persian ASR evaluation manifest (JSONL) from a pinned public corpus.

FA-04 slice 2, [#513](https://github.com/MSKazemi/yazses/issues/513). `bench_persian.py`
consumes a JSONL manifest of ``{"id", "audio", "reference"}`` rows; this script produces
those rows from Corpus A (Mozilla Common Voice) and Corpus B (Google FLEURS ``fa_ir``)
of `design/specs/persian-benchmark-and-validation.md` §2, so the numbers a result
publishes trace to a named, pinned, publicly reproducible corpus rather than to
whatever happened to be on one disk.

Pinning, per §2 and §8:

- The corpus revision/split live in the ``PINS`` constants below and travel into every
  manifest's sidecar metadata; a result built from the manifest stamps them on. A new
  corpus release is a one-line edit **and a new manifest**, never a silent drift.
- ``--limit N --seed S`` selects rows with a seeded PRNG *before any decode* — the §8
  rule that sampling is defined before model outputs exist — and the selection is
  recorded (rule, seed, limit) beside the rows it produced. No flag means the full
  split; there is no implicit subsampling to discover later.

**No audio is committed.** The manifest names audio paths on the local disk; the tests
build tiny synthetic corpus trees in a temporary directory. The no-audio-in-git
property is enforced structurally by ``tests/test_fa_manifest.py``, which walks the
repository for committed audio files and archives.

Both corpora are read with the standard library alone. FLEURS publishes per-language
TSV metadata plus a tar of WAVs; Common Voice publishes TSV metadata next to a clip
tree. ``pyarrow``/``datasets`` would both add a supply-chain surface to a step whose
job is to *name files*, and the spec's provenance requirement is about the pins, not
the reader.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
import unicodedata
from pathlib import Path

#: Everything §2 pins about each corpus, verbatim into the sidecar metadata and then
#: into the result's corpus block. A corpus "version" that is only ever a local
#: directory name is not a pin; these are.
PINS = {
    "fleurs": {
        # The HF dataset repo commit the metadata TSVs were read from. The audio
        # tars under data/fa_ir/audio/ are immutable at that commit.
        "dataset": "google/fleurs",
        "revision": "70bb2e84b976b7e960aa89f1c648e09c59f894dd",
        "config": "fa_ir",
        "split": "test",
        "metadata": "data/fa_ir/test.tsv",
        "audio_archive": "data/fa_ir/audio/test.tar.gz",
        # SHA-256 of that archive (657,317,725 bytes), as the Hub's LFS metadata
        # records it at the pinned revision. `main` refuses a different file.
        "audio_archive_sha256": "f787ae225da693ed28c734c18aac1932c0f271473c3fb49a98db5e9b222fa11d",
        "license": "CC-BY-4.0",
        "n_examples": 871,
    },
    "common-voice": {
        # Common Voice moved behind Mozilla Data Collective in Oct 2025. The
        # mozilla-foundation HF repo serves only .gitattributes+README anonymously
        # (gated), so the read path is pinned to the verified ungated community
        # mirror fsicoli/common_voice_17_0: LFS sha256-verified archive, CC0-1.0.
        "dataset": "fsicoli/common_voice_17_0",
        "revision": "8262c16bf297c87a9cd88c51997c4758ed7a8ba2",
        "config": "fa",
        "split": "test",
        "metadata": "transcript/fa/test.tsv",
        "audio_archive": "audio/fa/test/fa_test_0.tar",
        "audio_archive_sha256": "50ae3fd4c2c1d4835a57b6295a87af69d91c7e4bc3c65fe2c6347f876d7d639b",
        "license": "CC0-1.0",
    },
}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _clean_reference(text: str) -> str:
    """The reference column exactly as the corpus ships it, NFC-normalised.

    NFC only: §6 makes further normalisation the *scorer's* business (fa-eval-v1
    runs there), so the manifest must not pre-flatten what the benchmark exists to
    measure. NFC is idempotent and loss-free on text both corpora already ship in
    NFC, and a row that needed it is fixed rather than flagged: an evaluation
    normalizer applied *to the reference* at scoring time is the same fa-eval-v1
    that will be applied to the hypothesis, which is exactly the symmetry §6 wants.
    """
    return unicodedata.normalize("NFC", text).strip()


def _select(rows: list[dict], limit: int | None, seed: int | None) -> tuple[list[dict], dict]:
    """§8 sampling: the rule is fixed before any model output exists.

    Without ``limit`` the whole split is kept in the corpus' own order (itself
    deterministic at a pinned revision). With ``limit``, rows are selected without
    replacement so no utterance is scored twice under one manifest — duplicates would
    weight those rows in the average — and a missing ``seed`` means seed 0, which is
    recorded as such rather than left implicit.
    """
    if limit is None or limit >= len(rows):
        return rows, {"rule": "all rows in corpus order", "limit": None, "seed": None}
    rng = random.Random(seed if seed is not None else 0)
    picked = sorted(rng.sample(range(len(rows)), limit))
    selection = {
        "rule": f"seeded sample without replacement ({len(picked)} of {len(rows)})",
        "limit": limit,
        "seed": seed if seed is not None else 0,
    }
    return [rows[i] for i in picked], selection


# ── FLEURS ────────────────────────────────────────────────────────────────────

#: Column order of the FLEURS per-language TSVs. The files carry **no header** —
#: these are the names the official TFDS builder gives the same columns — so the
#: reader zips positions instead of trusting a first line that would silently eat
#: a real utterance (row 0 of test.tsv is data: `1735\t7913564082410055971.wav\t…`).
_FLEURS_COLUMNS = (
    "id",
    "filename",
    "raw_transcription",   # with punctuation — the column the manifest carries
    "transcription",       # punctuation stripped by the corpus itself
    "char_transcription",
    "num_samples",
    "gender",
)


def build_fleurs_rows(corpus_root: Path, limit: int | None, seed: int | None):
    """Rows from an extracted FLEURS ``fa_ir`` tree.

    Layout at the pinned revision: ``data/fa_ir/test.tsv`` (headerless, columns
    per ``_FLEURS_COLUMNS``) and ``data/fa_ir/audio/test.tar.gz`` whose members are
    ``test/<id>.wav``.

    **Which reference column** is a scoring decision, not a detail: FLEURS carries
    ``raw_transcription`` (punctuation kept) and ``transcription`` (punctuation
    stripped by the corpus). `bench_persian.py` reports raw *and*
    fa-eval-v1-normalized WER precisely so the normalizer's work stays visible
    (§5: “never report only normalized WER”); feeding it an already
    punctuation-stripped reference would zero the raw column’s headroom and
    flatter every model. The manifest therefore carries the **raw** column and
    the evaluation normalizer does §6’s work on it downstream.
    """
    tsv = corpus_root / "data" / "fa_ir" / "test.tsv"
    tar_path = corpus_root / "data" / "fa_ir" / "audio" / "test.tar.gz"
    if not tsv.is_file():
        raise SystemExit(
            f"FLEURS metadata not found: {tsv}\n"
            "Download at the pinned revision (see PINS['fleurs']) and keep the tree "
            "layout: data/fa_ir/test.tsv beside data/fa_ir/audio/test.tar.gz."
        )
    rows: list[dict] = []
    # The TSVs are not quoted: `"` is ordinary text. The default dialect would let a
    # field that starts with one swallow the tabs and rows after it, which is exactly
    # how a benchmark silently loses or merges utterances.
    with tsv.open(encoding="utf-8", newline="") as fh:
        for fields in csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            if len(fields) < len(_FLEURS_COLUMNS):
                raise SystemExit(
                    f"{tsv}: expected {len(_FLEURS_COLUMNS)} tab-separated columns, "
                    f"got {len(fields)}: {fields[:2]}… — the pinned TSV layout has "
                    "changed; do not guess, update PINS and this reader together."
                )
            rec = dict(zip(_FLEURS_COLUMNS, fields))
            wav_id = rec["filename"].removesuffix(".wav")
            rows.append(
                {
                    "id": f"fleurs-fa_ir-test-{wav_id}",
                    # Member path inside the audio tar; --audio-root rewrites the
                    # audio column to wherever the tree is extracted locally, so
                    # audio never needs to live inside git.
                    "audio": f"test/{rec['filename']}",
                    "reference": _clean_reference(rec["raw_transcription"]),
                }
            )
    rows, selection = _select(rows, limit, seed)
    meta = {
        "corpus": "fleurs",
        **{k: v for k, v in PINS["fleurs"].items()},
        "selection": selection,
        "generated_by": "paper/benchmark/make_fa_manifest.py",
        "n_rows": len(rows),
    }
    return rows, meta, tar_path


# ── Common Voice ──────────────────────────────────────────────────────────────


def build_cv_rows(corpus_root: Path, limit: int | None, seed: int | None):
    """Rows from an extracted Common Voice ``fa`` tree (pinned release).

    Layout at the pinned revision: ``test.tsv`` — columns include ``path`` (clip
    file name), ``sentence`` (the validated reference) — beside ``clips/`` holding
    the clips transcoded to 16 kHz mono WAV. Common Voice publishes 48 kHz mp3;
    the decode path (`_common.load_audio`) asserts 16 kHz like every other cell,
    so the transcode is corpus prep, recorded here rather than hidden in one
    contributor's shell history::

        ffmpeg -i clips_src/X.mp3 -ac 1 -ar 16000 clips/X.wav

    The transcode is loss-free for scoring: WER reads the decoded text, and the
    pinned archive's sha256 still proves which source bytes the tree came from.
    Only rows of the official test split are read: no re-splitting, so numbers
    stay comparable across contributors (§2's "fixed split" is Mozilla's, not
    ours).
    """
    tsv = corpus_root / "test.tsv"
    if not tsv.is_file():
        raise SystemExit(
            f"Common Voice metadata not found: {tsv}\n"
            "Download the pinned fa release (see PINS['common-voice']) and keep its "
            "tree layout: test.tsv beside clips/."
        )
    rows: list[dict] = []
    with tsv.open(encoding="utf-8", newline="") as fh:
        # Unquoted TSV, as above: sentences can start with or contain a `"`.
        for rec in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            sentence = (rec.get("sentence") or "").strip()
            if not sentence:
                # An empty reference is unscoreable (bench_persian drops the pair);
                # dropping it here, counted, is more honest than emitting a row
                # whose silence later shows up as a skipped pair.
                continue
            rows.append(
                {
                    "id": f"cv-fa-test-{Path(rec['path']).stem}",
                    "audio": f"clips/{Path(rec['path']).stem}.wav",
                    "reference": _clean_reference(sentence),
                }
            )
    rows, selection = _select(rows, limit, seed)
    meta = {
        "corpus": "common-voice",
        **{k: v for k, v in PINS["common-voice"].items()},
        "selection": selection,
        "generated_by": "paper/benchmark/make_fa_manifest.py",
        "n_rows": len(rows),
    }
    return rows, meta, corpus_root / Path(PINS["common-voice"]["audio_archive"]).name


# ── emission ──────────────────────────────────────────────────────────────────


def write_manifest(out_path: Path, rows: list[dict], meta: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    sidecar = out_path.with_suffix(out_path.suffix + ".meta.json")
    sidecar.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def validate_rows(rows: list[dict]) -> None:
    """The contract `bench_persian.py` depends on, checked before anything is written."""
    seen: set[str] = set()
    for i, row in enumerate(rows):
        missing = [k for k in ("id", "audio", "reference") if not row.get(k)]
        if missing:
            raise SystemExit(f"row {i} missing {missing}: {row}")
        if row["id"] in seen:
            raise SystemExit(f"duplicate id: {row['id']} (row {i})")
        seen.add(row["id"])
    if not rows:
        raise SystemExit("no rows selected — refusing to write an empty manifest")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("corpus", choices=("fleurs", "common-voice"))
    parser.add_argument("corpus_root", type=Path, help="extracted corpus tree (read-only)")
    parser.add_argument("out", type=Path, help="output JSONL path (.meta.json lands beside it)")
    parser.add_argument("--limit", type=int, default=None, help="§8 deterministic sample size")
    parser.add_argument("--seed", type=int, default=None, help="§8 selection seed (with --limit)")
    parser.add_argument(
        "--audio-root", type=Path, default=None,
        help="prefix written into the audio column (default: the corpus root itself)",
    )
    args = parser.parse_args(argv)

    if args.corpus == "fleurs":
        rows, meta, tar_path = build_fleurs_rows(args.corpus_root, args.limit, args.seed)
    else:
        rows, meta, tar_path = build_cv_rows(args.corpus_root, args.limit, args.seed)
    validate_rows(rows)

    root = args.audio_root if args.audio_root is not None else args.corpus_root
    for row in rows:
        row["audio"] = str(root / row["audio"])

    # Prove the pinned archive is the one these rows name before anyone spends
    # CPU-hours on it: a mismatch is the corpus drift the pins exist to prevent,
    # and it must stop the run, not be discovered at decode time. Without the
    # archive on disk the manifest can still be written (metadata only), but it
    # says so rather than looking verified.
    if tar_path is not None and tar_path.is_file():
        observed = _sha256_file(tar_path)
        pinned = PINS[meta["corpus"]]["audio_archive_sha256"]
        if observed != pinned:
            raise SystemExit(
                f"{tar_path}: sha256 {observed} does not match the pinned "
                f"{pinned}. This is not the archive at the pinned revision; "
                "re-download it, or update PINS (and issue a new manifest) if the "
                "corpus was deliberately re-pinned."
            )
        meta["audio_archive_sha256"] = observed
        meta["audio_archive_verified"] = True
    else:
        meta["audio_archive_verified"] = False
        print(
            "warning: corpus audio archive not found; manifest is metadata-only "
            "and its audio is NOT verified against the pin.",
            file=sys.stderr,
        )
    meta["n_rows"] = len(rows)

    write_manifest(args.out, rows, meta)
    print(
        f"{len(rows)} rows -> {args.out} (+ {args.out.with_suffix(args.out.suffix + '.meta.json').name})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
