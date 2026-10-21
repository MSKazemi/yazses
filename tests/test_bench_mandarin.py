"""MODEL-01 (#503): the Mandarin CER harness scores honestly and emits schema-valid JSON.

The issue's acceptance lines this file pins, each where it can be checked without a
model or a corpus:

- CER, not whitespace WER, is the metric -- and it is an exact Levenshtein count, split
  into substitutions, deletions and insertions;
- raw and script-normalized scores are distinguishable, and the script column is
  ``null`` (never a copy of another column) when OpenCC is absent;
- every result carries hardware/OS/runtime provenance and a weight-licence record;
- one command emits schema-valid result JSON with no audio and no model.

`mandarin_metrics.py` is stdlib-only, so its tests run on a plain `uv sync`;
`bench_mandarin.py` reaches `psutil` and skips without the benchmark group.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.benchmark_deps import load

BENCH = Path(__file__).resolve().parents[1] / "paper" / "benchmark"

#: A stand-in for OpenCC's t2s on exactly the characters the smoke set uses.
_T2S = str.maketrans({"們": "们", "學": "学", "習": "习", "漢": "汉", "語": "语"})


def _fake_opencc():
    return SimpleNamespace(
        __version__="test-table",
        OpenCC=lambda config: SimpleNamespace(convert=lambda text: text.translate(_T2S)),
    )


def _absent_opencc():
    raise ModuleNotFoundError("No module named 'opencc'", name="opencc")


@pytest.fixture(scope="module")
def mm():
    return load("mandarin_metrics", "mandarin_metrics.py")


@pytest.fixture(scope="module")
def bm():
    return load("bench_mandarin", "bench_mandarin.py")


# -- zh-eval-v1, rule by rule -----------------------------------------------------


def test_nfc_is_applied(mm):
    # U+F900 is a CJK compatibility ideograph; NFC maps it to the unified U+8C48.
    assert mm.normalize_zh_eval_v1("豈") == "豈"


def test_compatibility_characters_are_not_nfkc_folded(mm):
    assert mm.normalize_zh_eval_v1("①²㎏", keep_punctuation=True) == "①²㎏"


def test_full_width_ascii_folds_to_ascii(mm):
    assert mm.normalize_zh_eval_v1("ＡＢＣ１２３，", keep_punctuation=True) == "abc123,"


def test_half_width_cjk_punctuation_folds_to_its_ordinary_form(mm):
    assert mm.fold_width("｡｢｣､") == "。「」、"


def test_latin_is_case_folded(mm):
    assert mm.normalize_zh_eval_v1("我用iPhone") == mm.normalize_zh_eval_v1("我用IPHONE")


def test_every_kind_of_whitespace_is_removed(mm):
    # ASCII space, ideographic space U+3000, NBSP, tab, newline.
    assert mm.normalize_zh_eval_v1("你 好　世 界\t。\n") == "你好世界"


def test_punctuation_is_dropped_but_symbols_are_kept(mm):
    n = mm.normalize_zh_eval_v1
    assert n("「你好」、世界！？…—") == "你好世界"
    assert n("¥100+5°") == "¥100+5°"
    assert n("50%") == "50", "% is category Po and is documented as dropped"


def test_the_punct_view_keeps_punctuation(mm):
    assert mm.normalize_zh_eval_v1("你好，世界。", keep_punctuation=True) == "你好,世界。"


def test_digits_are_not_folded_to_han_numerals(mm):
    n = mm.normalize_zh_eval_v1
    assert n("2024年") != n("二零二四年")


def test_the_normalizer_is_idempotent(mm):
    for text in ("你好，世界。", "我用 iPhone 拍照", "ＡＢＣ　「x」", "¥100%"):
        once = mm.normalize_zh_eval_v1(text)
        assert mm.normalize_zh_eval_v1(once) == once


def test_the_script_converter_runs_before_punctuation_is_dropped(mm):
    """A converter that emitted punctuation must not be able to undo rule 5."""
    out = mm.normalize_zh_eval_v1("們", script_converter=lambda t: t.replace("們", "们。"))
    assert out == "们"


def test_evaluation_normalizer_does_not_import_production_code(mm):
    """Evaluation and production normalization drift independently (cf. fa-eval-v1)."""
    tree = ast.parse((BENCH / "mandarin_metrics.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(name.split(".")[0] in {"yazses", "opencc", "jiwer"} for name in imported), imported


# -- the alignment ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("ref", "hyp", "sdi"),
    [
        ("我今天去北京", "我今天去背景", (2, 0, 0)),
        ("今天天气很好", "今天天气真的很好", (0, 0, 2)),
        ("我想喝一杯咖啡", "我想喝咖啡", (0, 2, 0)),
        ("你好", "", (0, 2, 0)),
        ("", "你好", (0, 0, 2)),
        ("你好", "你好", (0, 0, 0)),
    ],
)
def test_align_splits_substitutions_deletions_and_insertions(mm, ref, hyp, sdi):
    c = mm.align(ref, hyp)
    assert (c.substitutions, c.deletions, c.insertions) == sdi
    assert c.hits + c.substitutions + c.deletions == c.ref_chars == len(ref)


def _levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def test_align_total_is_the_levenshtein_distance(mm):
    import random

    rng = random.Random(503)
    alphabet = "我你他们的了是不在有北京背景天气"
    for _ in range(300):
        a = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
        b = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
        c = mm.align(a, b)
        assert c.errors == _levenshtein(a, b), (a, b, c)
        assert c.hits + c.substitutions + c.deletions == len(a)
        assert c.hits + c.substitutions + c.insertions == len(b)


def test_corpus_cer_agrees_with_jiwer(mm, bm):
    jiwer = pytest.importorskip("jiwer")
    refs = [p["reference"] for p in bm.SMOKE_PAIRS]
    hyps = [p["hypothesis"] for p in bm.SMOKE_PAIRS]
    ours = mm.score(refs, hyps)["views"]["raw"]["cer"]
    assert ours == round(jiwer.cer(refs, hyps) * 100, 2)


# -- corpus scoring ----------------------------------------------------------------


def test_empty_references_are_skipped_from_every_view_and_counted(mm):
    s = mm.score(["", "你好"], ["多余", "你好"])
    assert s["n_pairs"] == 1 and s["n_skipped_empty"] == 1
    assert s["views"]["raw"]["ref_chars"] == s["views"]["normalized"]["ref_chars"] == 2
    assert s["per_utterance"][0] is None


def test_an_empty_hypothesis_is_all_deletions(mm):
    s = mm.score(["你好"], [""])
    assert s["views"]["raw"]["deletions"] == 2 and s["views"]["raw"]["cer"] == 100.0


def test_misaligned_or_empty_input_is_refused(mm):
    with pytest.raises(ValueError, match="align"):
        mm.score(["a"], [])
    with pytest.raises(ValueError, match="nothing"):
        mm.score([], [])


def test_without_a_converter_the_script_view_is_null_not_a_copy(mm):
    s = mm.score(["我们"], ["我們"])
    assert s["views"]["script"] is None and s["script_delta_cer"] is None


def test_with_a_converter_the_script_mismatch_is_separated_out(mm):
    s = mm.score(["我们学习汉语"], ["我們學習漢語"], script_converter=lambda t: t.translate(_T2S))
    assert s["views"]["normalized"]["substitutions"] == 5
    assert s["views"]["script"]["cer"] == 0.0
    assert s["script_delta_cer"] == s["views"]["normalized"]["cer"]


# -- the result document -------------------------------------------------------------


def test_the_smoke_document_validates_and_forces_the_views_apart(bm):
    doc = bm.run_smoke(importer=_absent_opencc)
    assert bm.validate_result(doc) == []
    m = doc["metrics"]
    assert m["cer_raw"] > m["cer_punct"] > m["cer_normalized"], m
    c = m["counts"]["raw"]
    assert (c["substitutions"], c["deletions"], c["insertions"]) == (9, 3, 4)


def test_smoke_without_opencc_records_a_no_op_fold(bm):
    doc = bm.run_smoke(importer=_absent_opencc)
    fold = doc["script_fold"]
    assert fold["applied"] is False and "opencc" in fold["reason"]
    assert doc["metrics"]["cer_script_normalized"] is None
    assert doc["metrics"]["counts"]["script"] is None


def test_smoke_with_opencc_reports_the_script_delta(bm):
    doc = bm.run_smoke(importer=_fake_opencc)
    assert bm.validate_result(doc) == []
    m = doc["metrics"]
    assert doc["script_fold"] == {
        "target": "simplified", "applied": True, "converter": "opencc t2s",
        "opencc_version": "test-table", "reason": None,
    }
    # The five wrong-script characters of smoke-003 are the whole difference.
    assert m["counts"]["normalized"]["substitutions"] - m["counts"]["script"]["substitutions"] == 5
    assert m["script_delta_cer"] == round(m["cer_normalized"] - m["cer_script_normalized"], 2) > 0


def test_traditional_references_fold_the_other_way(bm):
    seen = []
    fake = SimpleNamespace(OpenCC=lambda config: seen.append(config) or SimpleNamespace(convert=str))
    converter, record = bm.load_script_converter("traditional", lambda: fake)
    assert seen == ["s2t"] and record["converter"] == "opencc s2t"
    with pytest.raises(ValueError):
        bm.load_script_converter("klingon", _fake_opencc)
    assert bm.load_script_converter(None)[1]["applied"] is False


def test_the_document_carries_machine_and_runtime_provenance(bm):
    doc = bm.run_smoke(importer=_absent_opencc)
    for key in ("timestamp", "cpu_model", "os", "python", "yazses", "faster_whisper",
                "ctranslate2", "kernel", "ram_gb"):
        assert key in doc["provenance"], key
    assert doc["machine"]["cpu"] == doc["provenance"]["cpu_model"]


def test_the_licence_verdict_follows_from_the_licence(bm):
    assert bm.license_record("small", "abc", "MIT", "https://x")["in_permissive_allowlist"] is True
    assert bm.license_record("q", None, "Apache-2.0", "https://x")["in_permissive_allowlist"] is True
    custom = bm.license_record("sv", None, "LicenseRef-FunASR-Model", "https://x")
    assert custom["in_permissive_allowlist"] is False
    assert bm.license_record("echo", "0", None, None)["in_permissive_allowlist"] is None


def _tamper(bm, edit):
    doc = bm.run_smoke(importer=_fake_opencc)
    edit(doc)
    return bm.validate_result(doc)


def test_the_validator_rejects_a_hand_edited_number(bm):
    def edit(d):
        d["metrics"]["cer_normalized"] = 1.0
        d["metrics"]["counts"]["normalized"]["cer"] = 1.0
    assert any("cer_normalized" in p for p in _tamper(bm, edit))


def test_the_validator_rejects_inconsistent_counts(bm):
    def edit(d):
        d["metrics"]["counts"]["raw"]["hits"] += 1
    assert any("ref_chars" in p for p in _tamper(bm, edit))


def test_the_validator_rejects_a_script_column_without_a_fold(bm):
    def edit(d):
        d["script_fold"]["applied"] = False
    assert any("script view" in p for p in _tamper(bm, edit))


def test_the_validator_rejects_an_unearned_permissive_verdict(bm):
    def edit(d):
        d["model_license"]["license_id"] = "LicenseRef-custom"
        d["model_license"]["in_permissive_allowlist"] = True
    assert any("allowlist" in p for p in _tamper(bm, edit))


@pytest.mark.parametrize("key", ["model_license", "script_fold", "provenance", "metrics"])
def test_the_validator_requires_every_block(bm, key):
    assert any(key in p for p in _tamper(bm, lambda d: d.pop(key)))


def test_the_validator_rejects_a_foreign_schema(bm):
    assert any("schema" in p for p in _tamper(bm, lambda d: d.update(schema="other/1")))
    assert bm.validate_result({})


# -- selection ------------------------------------------------------------------------


def test_selection_is_a_function_of_seed_and_ids_only(bm):
    rows = [{"id": f"u{i:03d}"} for i in range(50)]
    a, rule = bm.select_rows(rows, 7, 10)
    b, _ = bm.select_rows(list(reversed(rows)), 7, 10)
    assert {r["id"] for r in a} == {r["id"] for r in b}
    assert len(a) == 10 and "sha256" in rule
    assert {r["id"] for r in bm.select_rows(rows, 8, 10)[0]} != {r["id"] for r in a}
    assert [r["id"] for r in a] == sorted(r["id"] for r in a), "decode order is manifest order"


def test_selection_without_a_limit_keeps_every_row(bm):
    rows = [{"id": "b"}, {"id": "a"}]
    assert bm.select_rows(rows, 0, None)[0] == rows
    assert bm.select_rows(rows, 0, 5)[0] == rows
    with pytest.raises(ValueError):
        bm.select_rows(rows, 0, 0)


# -- the manifest path (no model, no audio, no OpenCC) ----------------------------------


def _manifest(tmp_path: Path) -> Path:
    rows = [
        {"id": "z-1", "audio": "1.wav", "reference": "我们学习汉语"},
        {"id": "z-2", "audio": "2.wav", "reference": "今天天气很好"},
        {"id": "z-3", "audio": "3.wav", "reference": "你好，世界。"},
    ]
    manifest = tmp_path / "tiny-zh.jsonl"
    manifest.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                        encoding="utf-8")
    for r in rows:
        (tmp_path / r["audio"]).write_bytes(b"")
    (tmp_path / "tiny-zh.jsonl.meta.json").write_text(
        json.dumps({"license": "CC0-1.0", "consent": "public-corpus-licence"}), encoding="utf-8")
    return manifest


_HYPS = {"z-1": "我們學習漢語", "z-2": "今天天气真的很好", "z-3": "你好,世界"}


def _run(bm, tmp_path, **kw):
    manifest = _manifest(tmp_path)
    order = iter(["z-1", "z-2", "z-3"] if kw.get("limit") is None else kw.pop("_order"))
    kwargs = dict(
        license_id="MIT", license_source="https://github.com/openai/whisper#license",
        model_revision="rev-under-test",
        transcriber=lambda audio: _HYPS[next(order)],
        audio_loader=lambda path: [0.0] * 16000,
        importer=_fake_opencc, timestamp="2026-10-21T00:00:00Z",
    )
    kwargs.update(kw)
    return bm.run_manifest(manifest, "small", **kwargs)


def test_a_manifest_run_validates_and_records_what_it_scored(bm, tmp_path):
    hyps = tmp_path / "out" / "hyps.jsonl"
    doc = _run(bm, tmp_path, hyps_out=hyps)
    assert bm.validate_result(doc) == []
    assert doc["corpus"]["samples"] == 3 and doc["corpus"]["language"] == "zh"
    assert doc["model_license"]["license_id"] == "MIT"
    assert doc["model_license"]["revision"] == "rev-under-test"
    assert doc["model_license"]["in_permissive_allowlist"] is True
    for key in ("model_load_s", "peak_rss_mb", "decode_core_s", "audio_s"):
        assert key in doc["runtime"]
    assert doc["runtime"]["audio_s"] == 3.0
    assert doc["metrics"]["latency_p50_ms"] is not None
    lines = [json.loads(x) for x in hyps.read_text(encoding="utf-8").splitlines()]
    assert [x["id"] for x in lines] == ["z-1", "z-2", "z-3"]
    assert lines[0]["counts"]["raw"]["substitutions"] == 5
    assert lines[0]["counts"]["script"]["substitutions"] == 0


def test_a_limited_run_records_its_seed_and_limit(bm, tmp_path):
    chosen, _ = bm.select_rows([{"id": i} for i in ("z-1", "z-2", "z-3")], 3, 2)
    doc = _run(bm, tmp_path, seed=3, limit=2, _order=[r["id"] for r in chosen])
    sel = doc["selection"]
    assert (sel["seed"], sel["limit"], sel["n_manifest_rows"]) == (3, 2, 3)
    assert doc["corpus"]["samples"] == 2


@pytest.mark.parametrize("missing", ["license_id", "license_source"])
def test_a_manifest_run_without_a_licence_record_is_refused(bm, tmp_path, missing):
    with pytest.raises(SystemExit, match="licence"):
        _run(bm, tmp_path, **{missing: " "})


def test_manifest_mode_builds_a_zh_engine_with_production_conversion_off(bm, monkeypatch):
    from yazses.config import SttConfig

    seen = []

    class FasterWhisperEngine:
        pass

    monkeypatch.setattr("yazses.stt.factory.build_engine",
                        lambda stt: seen.append(stt) or FasterWhisperEngine())
    bm._build_checked("faster-whisper", "small", 4)
    (stt,) = seen
    assert isinstance(stt, SttConfig)
    assert (stt.engine, stt.model, stt.language, stt.cpu_threads) == ("faster-whisper", "small", "zh", 4)
    assert not stt.chinese_script, "the raw column must be the model's own output"


def test_manifest_mode_refuses_a_silently_substituted_engine(bm, monkeypatch):
    class FasterWhisperEngine:
        pass

    monkeypatch.setattr("yazses.stt.factory.build_engine", lambda stt: FasterWhisperEngine())
    with pytest.raises(RuntimeError, match="under another"):
        bm._build_checked("parakeet", "whatever", 0)


def test_build_engine_gets_one_positional_stt_config():
    tree = ast.parse((BENCH / "bench_mandarin.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "build_engine"]
    assert calls
    assert all(len(c.args) == 1 and not c.keywords for c in calls)


def test_the_smoke_path_never_reaches_an_engine_or_audio():
    src = (BENCH / "bench_mandarin.py").read_text(encoding="utf-8")
    smoke_fn = src.split("def run_smoke(")[1].split("\ndef ")[0]
    assert "build_engine" not in smoke_fn and "load_audio" not in smoke_fn


# -- the CLI ------------------------------------------------------------------------------


def test_one_command_emits_schema_valid_json(bm):
    r = subprocess.run([sys.executable, str(BENCH / "bench_mandarin.py"), "--smoke"],
                       capture_output=True, text=True, encoding="utf-8", timeout=60,
                       cwd=str(BENCH))
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert bm.validate_result(doc) == []
    assert doc["metrics"]["evaluation_normalizer"] == "zh-eval-v1"


def test_the_cli_refuses_a_manifest_run_without_a_licence(bm, tmp_path):
    manifest = _manifest(tmp_path)
    r = subprocess.run([sys.executable, str(BENCH / "bench_mandarin.py"), "--manifest",
                        str(manifest)], capture_output=True, text=True, encoding="utf-8",
                       timeout=60, cwd=str(BENCH))
    assert r.returncode != 0 and "licence" in r.stderr
