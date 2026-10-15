"""FA-04 (#513): the manifest gate, the injected-transcriber runner, and the scoring rules.

Everything here is synthetic: audio files are empty placeholders that are never decoded
(the loader is injected), and the transcripts are short Persian strings written for the
test. Nothing touches the network, a model, or a home/XDG directory (tmp_path only).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from tests.benchmark_deps import load

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "paper" / "benchmark"

# می‌خواهم (with ZWNJ), the same word without it, and a Latin-digit / Persian-digit pair.
MIKHAHAM = "می‌خواهم"
MIKHAHAM_NO_ZWNJ = "میخواهم"
AMADE = "آمده"
SALAM = "سلام"
DONYA = "دنیا"


@pytest.fixture(scope="module")
def pm():
    return load("persian_manifest", "persian_manifest.py")


@pytest.fixture(scope="module")
def metrics():
    return load("persian_metrics", "persian_metrics.py")


@pytest.fixture(scope="module")
def bp():
    # bench_persian imports persian_manifest by bare name; load() put it on sys.path.
    load("persian_manifest", "persian_manifest.py")
    return load("bench_persian", "bench_persian.py")


def write_manifest(
    dirpath: Path,
    rows: list[dict],
    meta: dict | None = None,
    name: str = "m.jsonl",
    touch: bool = True,
) -> Path:
    manifest = dirpath / name
    manifest.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    if meta is not None:
        (dirpath / (name + ".meta.json")).write_text(json.dumps(meta), encoding="utf-8")
    if touch:
        for r in rows:
            a = r.get("audio")
            if isinstance(a, str) and not os.path.isabs(a) and not a.startswith(".."):
                (dirpath / a).parent.mkdir(parents=True, exist_ok=True)
                (dirpath / a).write_bytes(b"")
    return manifest


GOOD_META = {"license": "CC0-1.0", "consent": "public-corpus-licence"}


def row(i: int = 1, **extra) -> dict:
    return {"id": f"r{i}", "audio": f"a{i}.wav", "reference": f"{SALAM} {DONYA}", **extra}


# ── the manifest gate ────────────────────────────────────────────────────────


def test_a_complete_manifest_loads(pm, tmp_path):
    m = write_manifest(
        tmp_path, [row(1, speaker="spk_01", session="s-7"), row(2)], GOOD_META
    )
    loaded = pm.load_manifest(m)
    assert [e.id for e in loaded.entries] == ["r1", "r2"]
    first = loaded.entries[0]
    assert first.audio == (tmp_path / "a1.wav").resolve()
    assert (first.speaker, first.session) == ("spk_01", "s-7")
    assert first.license == "CC0-1.0" and first.consent == "public-corpus-licence"
    assert loaded.entries[1].speaker is None
    assert len(loaded.sha256) == 64


def test_no_sidecar_means_no_licence_and_no_consent(pm, tmp_path):
    m = write_manifest(tmp_path, [row()], meta=None)
    with pytest.raises(pm.ManifestError) as exc:
        pm.load_manifest(m)
    assert "no licence" in str(exc.value) and "no consent" in str(exc.value)


@pytest.mark.parametrize("missing", ["license", "consent"])
def test_each_of_licence_and_consent_is_required(pm, tmp_path, missing):
    meta = {k: v for k, v in GOOD_META.items() if k != missing}
    m = write_manifest(tmp_path, [row()], meta)
    word = "licence" if missing == "license" else "consent"
    with pytest.raises(pm.ManifestError, match=f"no {word}"):
        pm.load_manifest(m)


@pytest.mark.parametrize("placeholder", ["", "  ", "None", "unknown", "TBD", "n/a"])
def test_a_placeholder_is_not_a_licence(pm, tmp_path, placeholder):
    m = write_manifest(tmp_path, [row()], {**GOOD_META, "license": placeholder})
    with pytest.raises(pm.ManifestError, match="no licence"):
        pm.load_manifest(m)


def test_a_row_may_carry_its_own_licence_and_consent(pm, tmp_path):
    m = write_manifest(
        tmp_path,
        [row(1, license="CC-BY-4.0", consent="participant-consent"), row(2)],
        GOOD_META,
    )
    got = pm.load_manifest(m).entries
    assert (got[0].license, got[0].consent) == ("CC-BY-4.0", "participant-consent")
    assert (got[1].license, got[1].consent) == ("CC0-1.0", "public-corpus-licence")


def test_a_blank_row_value_does_not_hide_the_sidecar_gap(pm, tmp_path):
    m = write_manifest(tmp_path, [row(1, consent="none")], {"license": "CC0-1.0"})
    with pytest.raises(pm.ManifestError, match="no consent"):
        pm.load_manifest(m)


def test_audio_outside_the_manifest_directory_is_refused(pm, tmp_path):
    root = tmp_path / "set"
    root.mkdir()
    (tmp_path / "secret.wav").write_bytes(b"")
    m = write_manifest(root, [row(1, audio="../secret.wav")], GOOD_META)
    with pytest.raises(pm.ManifestError, match="outside the audio root"):
        pm.load_manifest(m)


def test_an_absolute_path_outside_the_root_is_refused(pm, tmp_path):
    root = tmp_path / "set"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere.wav"
    elsewhere.write_bytes(b"")
    m = write_manifest(root, [row(1, audio=str(elsewhere))], GOOD_META)
    with pytest.raises(pm.ManifestError, match="outside the audio root"):
        pm.load_manifest(m)


def test_a_symlink_that_escapes_the_root_is_refused(pm, tmp_path):
    root = tmp_path / "set"
    root.mkdir()
    target = tmp_path / "outside.wav"
    target.write_bytes(b"")
    try:
        (root / "link.wav").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable here")
    m = write_manifest(root, [row(1, audio="link.wav")], GOOD_META, touch=False)
    with pytest.raises(pm.ManifestError, match="outside the audio root"):
        pm.load_manifest(m)


def test_an_explicit_audio_root_authorises_a_corpus_elsewhere(pm, tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    absolute = corpus / "x.wav"
    absolute.write_bytes(b"")
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    m = write_manifest(manifests, [row(1, audio=str(absolute))], GOOD_META)
    with pytest.raises(pm.ManifestError):
        pm.load_manifest(m)  # default root is the manifest's own directory
    assert pm.load_manifest(m, audio_root=corpus).entries[0].audio == absolute.resolve()
    # ...and the explicit root is still a boundary, not a blanket permission.
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(pm.ManifestError, match="outside the audio root"):
        pm.load_manifest(m, audio_root=other)


def test_missing_audio_is_refused_before_any_decode(pm, tmp_path):
    m = write_manifest(tmp_path, [row()], GOOD_META, touch=False)
    with pytest.raises(pm.ManifestError, match="does not exist"):
        pm.load_manifest(m)


@pytest.mark.parametrize("ok", ["spk_01", "S-7", "a" * 64, "0f3a"])
def test_opaque_pseudonyms_pass(pm, tmp_path, ok):
    m = write_manifest(tmp_path, [row(1, speaker=ok, session=ok)], GOOD_META)
    assert pm.load_manifest(m).entries[0].speaker == ok


@pytest.mark.parametrize(
    "bad",
    ["Ali Rezaei", "ali@example.org", "علی", "a" * 65, "", 7],
    ids=["spaced-name", "email", "persian-name", "too-long", "empty", "int"],
)
def test_a_name_or_address_is_not_a_pseudonym(pm, tmp_path, bad):
    m = write_manifest(tmp_path, [row(1, speaker=bad)], GOOD_META)
    with pytest.raises(pm.ManifestError, match="opaque pseudonym"):
        pm.load_manifest(m)


def test_structural_problems_are_refused(pm, tmp_path):
    dup = write_manifest(tmp_path, [row(1), {**row(2), "id": "r1"}], GOOD_META, "d.jsonl")
    with pytest.raises(pm.ManifestError, match="duplicate id"):
        pm.load_manifest(dup)
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(pm.ManifestError, match="not valid JSON"):
        pm.load_manifest(bad)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(pm.ManifestError, match="no rows"):
        pm.load_manifest(empty)
    no_ref = write_manifest(tmp_path, [{"id": "x", "audio": "a1.wav"}], GOOD_META, "n.jsonl")
    (tmp_path / "a1.wav").write_bytes(b"")
    with pytest.raises(pm.ManifestError, match="reference"):
        pm.load_manifest(no_ref)


def test_refusal_lists_every_problem_and_caps_the_listing(pm, tmp_path):
    rows = [row(i, audio="../nope.wav") for i in range(1, 16)]
    m = write_manifest(tmp_path, rows, None, touch=False)
    with pytest.raises(pm.ManifestError) as exc:
        pm.load_manifest(m)
    msg = str(exc.value)
    assert "45 problem(s)" in msg  # 15 rows x (licence, consent, path)
    assert "and 35 more" in msg
    assert msg.count("\n  ") <= 11


# ── the runner: an injected transcriber, no model, no audio decoder ───────────


def fake_loader(path):
    import numpy as np

    return np.zeros(16000, dtype=np.float32)


def run(bp, manifest, transcriber, **kw):
    return bp.run_manifest(
        manifest,
        "faster-whisper:small",
        transcriber=transcriber,
        audio_loader=fake_loader,
        timestamp="2026-01-01T00:00:00Z",
        **kw,
    )


def test_injected_transcriber_end_to_end_is_schema_valid(bp, tmp_path, monkeypatch):
    def no_engine(*a, **k):
        raise AssertionError("an injected transcriber must not build an engine")

    monkeypatch.setattr("yazses.stt.factory.build_engine", no_engine)
    m = write_manifest(
        tmp_path,
        [row(1), row(2, reference=f"{MIKHAHAM} {AMADE}")],
        {
            **GOOD_META,
            "dataset": "synthetic",
            "revision": "r0",
            "split": "dev",
            "selection": {"rule": "seeded sample without replacement (2 of 9)", "seed": 7, "limit": 2},
        },
    )
    hyps = iter([f"{SALAM} {DONYA}", f"{MIKHAHAM_NO_ZWNJ} {AMADE}"])
    doc = run(bp, m, lambda audio: next(hyps))

    assert bp.validate_result(doc) == []
    assert doc["corpus"]["samples"] == 2 and doc["corpus"]["split"] == "dev"
    assert doc["corpus"]["licenses"] == ["CC0-1.0"]
    assert doc["corpus"]["consents"] == ["public-corpus-licence"]
    # The seed and the hash of the selection travel in the artifact (#513, spec §8).
    assert doc["selection"]["seed"] == 7 and doc["selection"]["limit"] == 2
    assert doc["selection"]["rule"].startswith("seeded sample")
    assert len(doc["selection"]["rows_sha256"]) == 64
    assert doc["manifest"]["sha256"] == bp.load_manifest(m).sha256
    assert doc["manifest"]["pins"] == {"dataset": "synthetic", "revision": "r0"}
    # Raw and normalized are both there and both see the dropped ZWNJ.
    assert doc["metrics"]["wer_raw"] == doc["metrics"]["wer_normalized"] == 25.0
    assert doc["metrics"]["tokenisation"].startswith("wer: whitespace")
    # Provenance: CPU/OS/versions come from the shared collector, not re-derived here.
    assert doc["machine"]["cpu"] and doc["provenance"]["python"]


def test_the_artifact_is_deterministic_apart_from_measurements(bp, tmp_path):
    m = write_manifest(tmp_path, [row(1), row(2)], GOOD_META)

    def once():
        doc = run(bp, m, lambda audio: f"{SALAM} {DONYA}")
        for key in ("rtf", "latency_p50_ms", "latency_p95_ms"):
            doc["metrics"].pop(key)
        for key in ("runtime", "provenance"):
            doc.pop(key)
        return bp.dumps_result(doc)

    assert once() == once()
    blob = once()
    keys = list(json.loads(blob))
    assert keys == sorted(keys), "top-level keys must be serialised in sorted order"


def test_a_refused_manifest_stops_before_any_model_or_transcription(bp, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "yazses.stt.factory.build_engine", lambda stt: calls.append("engine")
    )
    m = write_manifest(tmp_path, [row()], {"license": "CC0-1.0"})  # no consent
    with pytest.raises(SystemExit, match="no consent"):
        bp.run_manifest(m, "faster-whisper:small", transcriber=lambda a: calls.append("t") or "")
    assert calls == []
    with pytest.raises(SystemExit, match="no consent"):
        bp.run_manifest(m, "faster-whisper:small")  # the real path is gated the same way
    assert calls == []


def test_hyps_out_carries_the_manifest_ids(bp, tmp_path):
    m = write_manifest(tmp_path, [row(1), row(2)], GOOD_META)
    out = tmp_path / "h" / "hyps.jsonl"
    run(bp, m, lambda audio: "x", hyps_out=out)
    got = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [g["id"] for g in got] == ["r1", "r2"]


def test_validator_checks_selection_and_manifest_blocks_when_present(bp):
    doc = bp.run_smoke()
    assert bp.validate_result(doc) == []
    doc["selection"]["seed"] = "seven"
    assert any("selection.seed" in p for p in bp.validate_result(doc))
    doc = bp.run_smoke()
    doc["manifest"] = {"sha256": 5}
    assert any("manifest.sha256" in p for p in bp.validate_result(doc))


def test_cli_refuses_audio_root_without_a_manifest():
    import subprocess

    r = subprocess.run(
        [sys.executable, str(BENCH / "bench_persian.py"), "--smoke", "--audio-root", "."],
        capture_output=True, text=True, timeout=60, cwd=str(BENCH),
    )
    assert r.returncode != 0 and "--audio-root" in r.stderr


# ── the scoring rules, one decision each (fa-eval-v1, documented in persian_metrics) ──


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ي", "ی"),            # Arabic Yeh -> Persian Yeh
        ("ى", "ی"),            # Alef Maksura -> Persian Yeh
        ("ك", "ک"),            # Arabic Kaf -> Keheh
        ("ئ", "ئ"),            # Yeh with hamza: a different letter, untouched
        ("یک", "یک"),  # already canonical
    ],
    ids=["yeh", "maqsura", "kaf", "hamza-yeh", "canonical"],
)
def test_letter_variant_rules(metrics, raw, expected):
    assert metrics.normalize_fa_eval_v1(raw) == expected


@pytest.mark.parametrize(
    "text",
    [
        "۱۲۳",            # Persian digits stay Persian
        "١٢٣",            # Arabic-Indic stay Arabic-Indic
        "123",                           # Latin stay Latin
        "ﺍﻩ",                  # presentation forms are not NFKC-folded
        "سـل",            # tatweel is kept
        "سَل",            # a diacritic (fatha) is kept
        "س‏ل",            # RLM is kept
        "می‌خ",      # ZWNJ is kept
    ],
    ids=["fa-digit", "ar-digit", "latin-digit", "presentation", "tatweel", "fatha", "rlm", "zwnj"],
)
def test_what_the_normalizer_deliberately_leaves_alone(metrics, text):
    assert metrics.normalize_fa_eval_v1(text) == text


def test_nbsp_and_runs_of_whitespace_become_one_space(metrics):
    assert metrics.normalize_fa_eval_v1(f" {SALAM}  {DONYA}\t\n") == f"{SALAM} {DONYA}"


def test_digit_family_difference_is_an_error_under_both_scorers(bp):
    out = bp.score_pairs(["۱۲"], ["12"], ["s"])
    assert out["wer_raw"] == out["wer_normalized"] == 100.0


def test_tokenisation_a_zwnj_compound_is_one_word_and_one_character(bp):
    ref = f"{MIKHAHAM} {AMADE}"
    hyp = f"{MIKHAHAM_NO_ZWNJ} {AMADE}"
    out = bp.score_pairs([ref], [hyp], ["s"])
    assert out["wer_raw"] == 50.0, "dropping the ZWNJ makes the whole compound a wrong word"
    # 13 code points in the reference (ZWNJ and the space count); one deletion.
    assert len(ref) == 13
    assert out["cer_raw"] == pytest.approx(100 / 13, abs=0.01)


def test_tokenisation_is_stated_in_the_metrics_module(metrics):
    assert "ZWNJ" in metrics.TOKENISATION and "code points" in metrics.TOKENISATION


def test_scoring_normalisation_never_reaches_product_code():
    """Metrics-only: no module under src/ may import the evaluation normalizer."""
    offenders = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "src").rglob("*.py")
        if "persian_metrics" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
