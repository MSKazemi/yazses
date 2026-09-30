"""Contract and property tests for FA-04 slice 2 (`make_fa_manifest.py`).

`design/specs/persian-benchmark-and-validation.md` demands:
- Corpus A (Mozilla Common Voice) and Corpus B (Google FLEURS fa_ir) supported.
- Pinned dataset revisions.
- Deterministic sampling before decoding (selection seed/hash recorded).
- No audio committed in git.

These tests prove all four properties with synthetic fixture files, without
requiring network access, large downloads, or git-tracked audio blobs.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCH = REPO_ROOT / "paper" / "benchmark"
TESTS_DIR = Path(__file__).resolve().parent

from tests.benchmark_deps import load

make_fa_manifest = load("make_fa_manifest", "make_fa_manifest.py")


@pytest.fixture
def fake_fleurs_tree(tmp_path: Path) -> Path:
    """A minimal FLEURS directory structure with a tiny test.tsv and dummy tar."""
    root = tmp_path / "fleurs"
    tsv_dir = root / "data" / "fa_ir"
    audio_dir = tsv_dir / "audio"
    tsv_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)

    tsv_file = tsv_dir / "test.tsv"
    # Header format of FLEURS TSVs (tab separated)
    # id, filename, raw_transcription, normalized_transcription, chars, num_samples, gender
    rows = [
        ["101", "101.wav", "محققان دانشگاه پرینستون آمریکا", "محققان دانشگاه پرینستون امریکا", "...", "518400", "MALE"],
        ["102", "102.wav", "شکلات داغ در حد استاندارد است.", "شکلات داغ در حد استاندارد است", "...", "193920", "MALE"],
        ["103", "103.wav", "آبمیوه‌ها گران‌قیمت ولی عالی می‌باشند.", "ابمیوهها گرانقیمت ولی عالی میباشند", "...", "205440", "FEMALE"],
        ["104", "104.wav", "چهارمین جمله آزمایشی برای نمونه‌گیری.", "چهارمین جمله ازمایشی برای نمونهگیری", "...", "210000", "FEMALE"],
        ["105", "105.wav", "پنجمین صدا برای تست انتخاب تصادفی.", "پنجمین صدا برای تست انتخاب تصادفی", "...", "180000", "MALE"],
    ]
    with tsv_file.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        # Headerless, like the real FLEURS TSVs (the reader zips column positions;
        # a header line here would be read as a sixth utterance).
        for r in rows:
            writer.writerow(r)

    # Empty dummy tar archive
    dummy_tar = audio_dir / "test.tar.gz"
    dummy_tar.write_bytes(b"dummy-tar-bytes")

    return root


@pytest.fixture
def fake_cv_tree(tmp_path: Path) -> Path:
    """A minimal Common Voice directory structure with a tiny test.tsv."""
    root = tmp_path / "cv"
    root.mkdir(parents=True)
    tsv_file = root / "test.tsv"
    rows = [
        {"client_id": "c1", "path": "clip_001.mp3", "sentence": "جمله اول تست برای کامن ویس.", "up_votes": "2", "down_votes": "0"},
        {"client_id": "c2", "path": "clip_002.mp3", "sentence": "صدای دوم با کاراکترهای نیم‌فاصله.", "up_votes": "3", "down_votes": "0"},
        {"client_id": "c3", "path": "clip_003.mp3", "sentence": " ", "up_votes": "2", "down_votes": "0"},  # empty, should skip
        {"client_id": "c4", "path": "clip_004.mp3", "sentence": "چهارمین ضبط شده در محیط آرام.", "up_votes": "4", "down_votes": "0"},
    ]
    with tsv_file.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["client_id", "path", "sentence", "up_votes", "down_votes"], delimiter="\t")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    (root / "clips").mkdir()
    return root


# ── Schema and Structure Tests ────────────────────────────────────────────────


def test_fleurs_rows_follow_contract(fake_fleurs_tree: Path, tmp_path: Path):
    out_jsonl = tmp_path / "fleurs.jsonl"
    argv = ["fleurs", str(fake_fleurs_tree), str(out_jsonl)]
    rc = make_fa_manifest.main(argv)
    assert rc == 0
    assert out_jsonl.is_file()

    # Check manifest JSONL lines
    lines = [json.loads(line) for line in out_jsonl.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 5
    for row in lines:
        assert set(row.keys()) == {"id", "audio", "reference"}
        assert row["id"].startswith("fleurs-fa_ir-test-")
        assert row["audio"].endswith(".wav")
        assert len(row["reference"]) > 0

    # Check sidecar metadata
    meta_path = out_jsonl.with_suffix(".jsonl.meta.json")
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["corpus"] == "fleurs"
    assert meta["config"] == "fa_ir"
    assert meta["split"] == "test"
    assert meta["revision"] == make_fa_manifest.PINS["fleurs"]["revision"]
    assert meta["n_rows"] == 5
    assert meta["selection"]["rule"] == "all rows in corpus order"


def test_common_voice_rows_skip_empty_references(fake_cv_tree: Path, tmp_path: Path):
    out_jsonl = tmp_path / "cv.jsonl"
    argv = ["common-voice", str(fake_cv_tree), str(out_jsonl)]
    rc = make_fa_manifest.main(argv)
    assert rc == 0

    lines = [json.loads(line) for line in out_jsonl.read_text(encoding="utf-8").splitlines() if line]
    # Out of 4 rows, 1 was empty sentence, so 3 valid rows
    assert len(lines) == 3
    ids = [r["id"] for r in lines]
    assert ids == ["cv-fa-test-clip_001", "cv-fa-test-clip_002", "cv-fa-test-clip_004"]


# ── Determinism & Sampling Tests (§8) ─────────────────────────────────────────


def test_sampling_determinism_with_seed(fake_fleurs_tree: Path, tmp_path: Path):
    out1 = tmp_path / "sample1.jsonl"
    out2 = tmp_path / "sample2.jsonl"

    make_fa_manifest.main(["fleurs", str(fake_fleurs_tree), str(out1), "--limit", "3", "--seed", "42"])
    make_fa_manifest.main(["fleurs", str(fake_fleurs_tree), str(out2), "--limit", "3", "--seed", "42"])

    # Must be byte-identical
    assert out1.read_bytes() == out2.read_bytes()
    assert out1.with_suffix(".jsonl.meta.json").read_bytes() == out2.with_suffix(".jsonl.meta.json").read_bytes()

    lines = [json.loads(line) for line in out1.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 3
    # Check that sample ids are unique
    assert len(set(r["id"] for r in lines)) == 3


def test_different_seeds_give_different_samples(fake_fleurs_tree: Path, tmp_path: Path):
    out1 = tmp_path / "sample_a.jsonl"
    out2 = tmp_path / "sample_b.jsonl"

    make_fa_manifest.main(["fleurs", str(fake_fleurs_tree), str(out1), "--limit", "2", "--seed", "1"])
    make_fa_manifest.main(["fleurs", str(fake_fleurs_tree), str(out2), "--limit", "2", "--seed", "999"])

    lines1 = [json.loads(l)["id"] for l in out1.read_text(encoding="utf-8").splitlines() if l]
    lines2 = [json.loads(l)["id"] for l in out2.read_text(encoding="utf-8").splitlines() if l]
    assert lines1 != lines2


# ── Structural & Anti-Leak Guards ─────────────────────────────────────────────


def test_pins_contain_all_required_keys():
    for name, pin in make_fa_manifest.PINS.items():
        assert "dataset" in pin
        assert "revision" in pin
        assert "split" in pin
        assert "metadata" in pin
        assert "license" in pin
        # Revision must look like a 40-char git commit SHA
        assert len(pin["revision"]) == 40


def test_no_real_audio_committed_in_git():
    """Verify that no actual corpus audio files (WAV, MP3, FLAC, TAR) are committed under paper/ or tests/."""
    forbidden_exts = {".wav", ".mp3", ".flac", ".tar.gz", ".tar"}
    for search_dir in (REPO_ROOT / "paper" / "benchmark", REPO_ROOT / "tests"):
        for p in search_dir.rglob("*"):
            if p.is_file() and p.suffix in forbidden_exts:
                raise AssertionError(f"Forbidden audio/archive file committed in repository: {p}")
