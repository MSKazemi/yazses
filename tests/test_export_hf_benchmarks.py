"""`scripts/export_hf_benchmarks.py` turns `paper/results/` into a Hugging Face dataset of tables.

The exporter is the only thing standing between the archived benchmark JSON and a public
dataset page, so these tests pin the properties a reader of that page relies on:

* **Byte-reproducible.**  Same inputs, same bytes -- no generation timestamp, stable order.
* **A missing value is empty, never `0`.**  A zero would read as a measurement.
* **Measurements and analyses never share a table.**  A `-significance` file decodes nothing;
  counting it beside the grid it analyses counts the same utterances twice.
* **Nothing sensitive and nothing outside the allowlist.**  Home paths, e-mail addresses and
  tokens abort the export; only `huggingface/benchmarks/data` is ever written.
* **Values are copied, not recomputed.**  Spot-checked against the real archived files.
* **The committed output is current.**  `--check` passes on the repository as it stands, and
  the directory is compared with the metadata in both directions, so an archive file that is
  neither exported nor excluded fails here instead of vanishing silently (an in-sync check on a
  generated file cannot notice an omission).

Everything but the last block runs on synthetic fixtures under `tmp_path`; no network, no audio.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_hf_benchmarks.py"
RESULTS = ROOT / "paper" / "results"
DATA = ROOT / "huggingface" / "benchmarks" / "data"
CARD = ROOT / "huggingface" / "benchmarks" / "README.md"


def _load():
    spec = importlib.util.spec_from_file_location("export_hf_benchmarks", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["export_hf_benchmarks"] = mod
    spec.loader.exec_module(mod)
    return mod


X = _load()


# --------------------------------------------------------------------------------------
# Synthetic archive
# --------------------------------------------------------------------------------------

PROV = {
    "timestamp": "2026-01-02T03:04:05Z",
    "cpu_model": "Test CPU 9000",
    "logical_cpus": 8,
    "ram_gb": 16.0,
    "os": "TestOS 1",
    "kernel": "1.2.3-test",
    "python": "3.12.0",
    "faster_whisper": "1.2.1",
    "yazses": "9.9.9",
    "numpy": "2.0.0",
    "ctranslate2": "4.0.0",
    "omp_num_threads": "unset",
    "load_average_1m": 0.5,
    "compute_type": "int8",
    "device": "cpu",
}

WER_DOC = """{
 "config": {"dataset": "Toy Corpus", "n_utterances": 10, "total_audio_seconds": 100.0,
            "selection": "first ten", "normalizer": "toy-norm"},
 "models": {
  "tiny": {"wer": 5.10, "mer": 5.0, "hits": 90, "substitutions": 5, "deletions": 3,
           "insertions": 2, "rtf_mean": 0.20, "rtf_median": 0.1, "rtf_p95": 0.5,
           "decode_seconds_total": 20.0, "load_seconds": 0.5, "realtime_speedup_median": 10.0,
           "engine": "toy-engine", "wer_ci95": [4.0, 6.5]},
  "bare": {"wer": 7.5}
 }
}"""

BEAM_DOC = """{
 "config": {"n_utterances": 10, "split": "toy-clean", "total_audio_seconds": 100.0},
 "rows": [
  {"model": "tiny", "beam_size": 1, "split": "toy-clean", "wer_pct": 5.0, "wer_ci95": [4.0, 6.0],
   "substitutions": 4, "deletions": 3, "insertions": 2, "decode_seconds": 9.5, "rtf": 0.095,
   "per_utt_errors": [1, 0], "per_utt_ref_words": [5, 5]},
  {"model": "tiny", "beam_size": 2, "split": "toy-clean", "wer_pct": 4.0,
   "per_utt_errors": [0, 0], "per_utt_ref_words": [5, 5]}
 ]
}"""

SIG_DOC = """{
 "alpha": 0.05, "method": "toy bootstrap", "n_comparisons": 1, "n_significant": 0,
 "source": "beam-toy.json",
 "comparisons": [{"a": "tiny beam=1", "b": "tiny beam=2", "split": "toy-clean",
                  "a_wer": 5.0, "b_wer": 4.0, "diff": 1.0, "diff_ci95": [-0.5, 2.5],
                  "p": 0.2, "n_utterances": 10}]
}"""

TOY_SOURCES = (
    X.Source("wer-toy.json", "asr_librispeech_wer", "wer"),
    X.Source("beam-toy.json", "beam_sweep", "beam", experiment="beam-test"),
    X.Source("beam-toy-significance.json", "significance_beam", "beam_significance",
             kind="significance_analysis", experiment="beam-test"),
)


def _write_json(path: Path, doc_text: str, **kw) -> None:
    # Re-serialise through Decimal so 5.10 stays 5.10 in the file as well.
    doc = json.loads(doc_text, parse_float=Decimal)
    doc["provenance"] = {k: v for k, v in (kw.get("prov") or PROV).items()
                         if k not in kw.get("drop", ())}

    def enc(v):
        if isinstance(v, Decimal):
            return format(v, "f")
        if isinstance(v, dict):
            return "{" + ",".join(f"{json.dumps(k)}:{enc(x)}" for k, x in v.items()) + "}"
        if isinstance(v, list):
            return "[" + ",".join(enc(x) for x in v) + "]"
        return json.dumps(v)

    path.write_text(enc(doc), encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    results = tmp_path / "paper" / "results"
    results.mkdir(parents=True)
    _write_json(results / "wer-toy.json", WER_DOC)
    _write_json(results / "beam-toy.json", BEAM_DOC)
    _write_json(results / "beam-toy-significance.json", SIG_DOC)
    _write_json(results / "unreviewed.json", '{"x": 1}')
    (results / "README.md").write_text("notes\n", encoding="utf-8")
    (results / "probes").mkdir()
    _write_json(results / "probes" / "probe.json", '{"x": 1}')
    return tmp_path


class FakeGit:
    """Stands in for GitInfo so the commit columns are exercised without a repository."""

    def commit(self, rel: str) -> str:
        return "c" * 40 if rel.endswith("wer-toy.json") else ""

    def revision(self, rels) -> str:
        return "r" * 40


def _build(repo: Path, sources=TOY_SOURCES, git=None):
    return X.build_export(repo, sources, git=git or FakeGit())


def _rows(export, table: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(export.files[f"{table}.csv"].decode("utf-8"), newline="")))


# --------------------------------------------------------------------------------------
# Determinism, formatting
# --------------------------------------------------------------------------------------


def test_two_runs_produce_identical_bytes(repo: Path) -> None:
    a, b = _build(repo), _build(repo)
    assert a.files == b.files
    X.write_export(a, repo)
    first = {p.name: p.read_bytes() for p in (repo / X.OUT_REL).iterdir()}
    X.write_export(_build(repo), repo)
    assert {p.name: p.read_bytes() for p in (repo / X.OUT_REL).iterdir()} == first


def test_output_has_no_generation_timestamp_and_unix_newlines(repo: Path) -> None:
    export = _build(repo)
    for name, data in export.files.items():
        assert b"\r" not in data, name
        assert data.endswith(b"\n"), name
    meta = export.metadata
    assert "generated" not in json.dumps(meta).lower()
    # The only timestamps anywhere are the ones copied from the sources.
    stamps = set(re.findall(rb"\d{4}-\d\d-\d\dT[\d:]+Z", b"".join(export.files.values())))
    assert stamps == {PROV["timestamp"].encode()}


def test_floats_keep_their_written_form(repo: Path) -> None:
    row = {r["model_key"]: r for r in _rows(_build(repo), "asr_librispeech_wer")}["tiny"]
    assert row["wer_pct"] == "5.10"  # not 5.1: the source wrote 5.10
    assert row["decode_seconds_total"] == "20.0"
    assert row["rtf_mean"] == "0.20"
    assert row["wer_ci95_low_pct"] == "4.0" and row["wer_ci95_high_pct"] == "6.5"


@pytest.mark.parametrize(("value", "cell"), [
    (None, ""), (True, "true"), (False, "false"), (7, "7"), (Decimal("1.0"), "1.0"),
    (Decimal("1E-7"), "0.0000001"), ("text", "text"),
    ({"b": Decimal("2.0"), "a": [1, None]}, '{"a":[1,null],"b":2.0}'),
])
def test_fmt(value, cell) -> None:
    assert X.fmt(value) == cell


def test_non_finite_numbers_are_rejected() -> None:
    with pytest.raises(X.ExportError, match="non-finite"):
        X.parse_json_text('{"a": NaN}', "x.json")


# --------------------------------------------------------------------------------------
# Missing is empty
# --------------------------------------------------------------------------------------


def test_a_missing_value_is_empty_never_zero(repo: Path) -> None:
    rows = {r["model_key"]: r for r in _rows(_build(repo), "asr_librispeech_wer")}
    bare = rows["bare"]
    assert bare["wer_pct"] == "7.5"
    for col in ("mer_pct", "hits", "substitutions", "deletions", "insertions", "rtf_mean",
                "rtf_median", "rtf_p95", "decode_seconds_total", "load_seconds",
                "wer_ci95_low_pct", "wer_ci95_high_pct", "engine", "model", "n_scored_utterances"):
        assert bare[col] == "", f"{col} must be empty when the source omits it, got {bare[col]!r}"
    # Provenance the toy files do not carry stays empty too: no stratification flag was
    # recorded, so none is invented.
    for col in ("corpus_sha256_16", "corpus_stratified", "corpus_version", "argv"):
        assert bare[col] == ""


def test_null_in_the_source_is_empty(repo: Path) -> None:
    results = repo / "paper" / "results"
    _write_json(results / "wer-toy.json", WER_DOC.replace('"mer": 5.0', '"mer": null'))
    row = {r["model_key"]: r for r in _rows(_build(repo), "asr_librispeech_wer")}["tiny"]
    assert row["mer_pct"] == ""


# --------------------------------------------------------------------------------------
# Measurements vs analyses
# --------------------------------------------------------------------------------------


def test_significance_rows_are_labelled_and_in_their_own_table(repo: Path) -> None:
    export = _build(repo)
    assert {r["record_kind"] for r in _rows(export, "significance_beam")} == {"significance_analysis"}
    assert {r["record_kind"] for r in _rows(export, "beam_sweep")} == {"measurement"}
    assert {r["record_kind"] for r in _rows(export, "asr_librispeech_wer")} == {"measurement"}
    sig = _rows(export, "significance_beam")[0]
    assert sig["analysis_of"] == "beam-toy.json"
    assert sig["p_value"] == "0.2" and sig["diff_a_minus_b_pct"] == "1.0"
    # the analysis' machine columns describe the host that ran the analysis; the reader is
    # pointed at the measurement through analysis_of, and no WER row appears in this table
    assert "rtf" not in _rows(export, "significance_beam")[0]
    assert export.metadata["tables"]["significance_beam"]["record_kind"] == "significance_analysis"


def test_a_significance_source_cannot_be_routed_to_a_measurement_table(repo: Path) -> None:
    bad = X.Source("beam-toy-significance.json", "beam_sweep", "beam_significance",
                   kind="significance_analysis")
    with pytest.raises(X.ExportError, match="cannot go in table"):
        X.build_export(repo, (bad,), git=FakeGit())


def test_parsers_refuse_the_wrong_file_shape(repo: Path) -> None:
    results = repo / "paper" / "results"
    swapped = (
        X.Source("beam-toy-significance.json", "beam_sweep", "beam"),
    )
    with pytest.raises(X.ExportError, match="beam-toy-significance.json"):
        X.build_export(repo, swapped, git=FakeGit())
    swapped = (
        X.Source("beam-toy.json", "significance_beam", "beam_significance",
                 kind="significance_analysis"),
    )
    with pytest.raises(X.ExportError, match="comparisons"):
        X.build_export(repo, swapped, git=FakeGit())
    assert (results / "beam-toy.json").is_file()


def test_every_real_significance_file_is_in_a_significance_table() -> None:
    meta = json.loads((DATA / X.METADATA_NAME).read_text(encoding="utf-8"))
    for src in meta["sources"]:
        is_analysis = "significance" in src["path"]
        assert (src["record_kind"] == "significance_analysis") == is_analysis, src["path"]
        for table in src["tables"]:
            assert meta["tables"][table]["record_kind"] == src["record_kind"], (src["path"], table)


# --------------------------------------------------------------------------------------
# Sensitive content
# --------------------------------------------------------------------------------------

_FAKE_SECRETS = {
    "home path": "/home/" + "alice" + "/corpus",
    "mac home path": "/Users/" + "bob" + "/x",
    "windows home path": "C:\\Users\\" + "carol" + "\\x",
    "e-mail": "someone" + "@" + "example.org",
    "hf token": "hf" + "_" + "A" * 30,
    "github token": "ghp" + "_" + "B" * 30,
    "openai-style key": "sk" + "-" + "C" * 30,
    "private tree": ".claude" + "/plans/secret.md",
    "strategy tree": "strategy" + "/launch.md",
}


@pytest.mark.parametrize("label", sorted(_FAKE_SECRETS))
def test_sensitive_strings_abort_the_export(repo: Path, label: str) -> None:
    secret = _FAKE_SECRETS[label]
    results = repo / "paper" / "results"
    doc = json.loads(WER_DOC, parse_float=Decimal)
    doc["config"]["selection"] = f"see {secret}"
    doc["provenance"] = dict(PROV)
    (results / "wer-toy.json").write_text(
        json.dumps(doc, default=float), encoding="utf-8")
    with pytest.raises(X.ExportError) as err:
        _build(repo)
    message = str(err.value)
    assert "wer-toy.json" in message and "config.selection" in message
    assert secret not in message, "the error must not echo the sensitive value"
    assert not (repo / X.OUT_REL).exists()


def test_a_sensitive_key_is_caught_too(repo: Path) -> None:
    results = repo / "paper" / "results"
    doc = json.loads(WER_DOC, parse_float=Decimal)
    doc["models"]["/home/" + "dave" + "/m"] = {"wer": 1.5}
    doc["provenance"] = dict(PROV)
    (results / "wer-toy.json").write_text(json.dumps(doc, default=float), encoding="utf-8")
    with pytest.raises(X.ExportError, match="home-directory path"):
        _build(repo)


@pytest.mark.parametrize("ok", [
    "$HOME/ami16_corpus", "paper/benchmark/bench_wer.py --n 200", "INTEL(R) XEON(R) PLATINUM 8573C",
    "tests/fixtures/commands/command_phrases.json", "0123456789abcdef" * 4, "design/adr/adr-019.md",
])
def test_ordinary_values_are_not_flagged(ok: str) -> None:
    assert X.scan_text(ok) == []


def test_the_real_archived_sources_pass_the_scan() -> None:
    for src in X.ALLOWLIST:
        doc = X.parse_json_text((RESULTS / src.path).read_text(encoding="utf-8"), src.path)
        X.scan_document(doc, src.path)


# --------------------------------------------------------------------------------------
# Allowlist and write fence
# --------------------------------------------------------------------------------------


def test_only_allowlisted_files_are_exported_and_the_rest_are_excluded_with_reasons(repo: Path) -> None:
    export = _build(repo)
    assert {s["path"] for s in export.metadata["sources"]} == {
        "paper/results/wer-toy.json", "paper/results/beam-toy.json",
        "paper/results/beam-toy-significance.json",
    }
    excluded = {e["path"]: e["reason"] for e in export.metadata["excluded"]}
    assert set(excluded) == {
        "paper/results/unreviewed.json", "paper/results/README.md",
        "paper/results/probes/probe.json",
    }
    assert all(reason.strip() for reason in excluded.values())
    assert "not reviewed" in excluded["paper/results/unreviewed.json"]
    assert "documentation" in excluded["paper/results/README.md"]
    assert "probe" in excluded["paper/results/probes/probe.json"]
    assert b"unreviewed" in export.files[X.METADATA_NAME]  # listed as excluded...
    for name, data in export.files.items():
        if name.endswith(".csv"):
            assert b"unreviewed.json" not in data  # ...but never exported as rows


def test_every_archive_file_is_exactly_one_of_included_or_excluded(repo: Path) -> None:
    export = _build(repo)
    archive = {f"paper/results/{p}" for p in X.list_archive(repo / X.RESULTS_REL)}
    included = {s["path"] for s in export.metadata["sources"]}
    excluded = {e["path"] for e in export.metadata["excluded"]}
    assert included | excluded == archive
    assert not included & excluded


def test_an_allowlisted_file_that_is_absent_is_an_error(repo: Path) -> None:
    ghost = (X.Source("nope.json", "vad_gate", "vad"),)
    with pytest.raises(X.ExportError, match="nope.json.*not present"):
        X.build_export(repo, ghost, git=FakeGit())


def test_a_path_escaping_the_results_directory_is_refused(repo: Path) -> None:
    (repo / "secret.json").write_text("{}", encoding="utf-8")
    sneaky = (X.Source("../../secret.json", "vad_gate", "vad"),)
    with pytest.raises(X.ExportError):
        X.build_export(repo, sneaky, git=FakeGit())


@pytest.mark.parametrize("target", [
    "paper/results", "paper/results/exported", "paper", "huggingface", "huggingface/benchmarks",
    "huggingface/benchmarks/data/..", ".", "elsewhere",
])
def test_writes_outside_the_data_directory_are_refused(repo: Path, target: str) -> None:
    export = _build(repo)
    before = {p: p.read_bytes() for p in (repo / "paper").rglob("*") if p.is_file()}
    with pytest.raises(X.ExportError, match="refusing"):
        X.write_export(export, repo, out_dir=repo / target)
    after = {p: p.read_bytes() for p in (repo / "paper").rglob("*") if p.is_file()}
    assert before == after, "paper/ must never be modified by the exporter"
    assert not (repo / "elsewhere").exists()


def test_a_normal_write_leaves_paper_untouched_and_removes_only_its_own_stale_files(
    repo: Path,
) -> None:
    before = {p: p.read_bytes() for p in (repo / "paper").rglob("*") if p.is_file()}
    out = repo / X.OUT_REL
    out.mkdir(parents=True)
    (out / "stale_table.csv").write_text("x\n", encoding="utf-8")
    (out / "notes.txt").write_text("keep me\n", encoding="utf-8")
    written = X.write_export(_build(repo), repo)
    assert "stale_table.csv" not in written
    assert not (out / "stale_table.csv").exists()
    assert (out / "notes.txt").exists()
    after = {p: p.read_bytes() for p in (repo / "paper").rglob("*") if p.is_file()}
    assert before == after


# --------------------------------------------------------------------------------------
# Provenance columns and malformed records
# --------------------------------------------------------------------------------------


def test_every_row_carries_the_provenance_columns(repo: Path) -> None:
    export = _build(repo)
    for table, meta in export.metadata["tables"].items():
        cols = meta["columns"]
        for needed in (
            "record_kind", "source_file", "source_sha256", "source_git_commit", "timestamp_utc",
            "machine", "machine_cpu_model", "machine_logical_cpus", "machine_os",
            "yazses_version", "faster_whisper_version", "corpus_name", "corpus_split", "corpus_n",
            "corpus_sha256_16", "corpus_stratified", "argv",
        ):
            assert needed in cols, (table, needed)
        for row in _rows(export, table):
            digest = hashlib.sha256(
                (repo / row["source_file"]).read_bytes()).hexdigest()
            assert row["source_sha256"] == digest
            assert row["machine_cpu_model"] == "Test CPU 9000"
            assert row["machine"] == "Test CPU 9000 / 8 logical CPUs / 16.0 GB / TestOS 1"
            assert row["yazses_version"] == "9.9.9"
            assert row["faster_whisper_version"] == "1.2.1"
            assert row["timestamp_utc"] == PROV["timestamp"]


def test_git_commit_is_recorded_or_explicitly_empty(repo: Path) -> None:
    rows = _rows(_build(repo), "asr_librispeech_wer")
    assert {r["source_git_commit"] for r in rows} == {"c" * 40}
    # no git at all (a bare temp directory): empty, not a guess
    bare = _rows(X.build_export(repo, TOY_SOURCES), "asr_librispeech_wer")
    assert {r["source_git_commit"] for r in bare} == {""}
    assert X.build_export(repo, TOY_SOURCES).metadata["source_revision"] == ""


def test_the_recorded_commit_is_the_fallback_when_git_cannot_answer(repo: Path) -> None:
    git = X.GitInfo(repo, {"paper/results/wer-toy.json": "f" * 40}, "e" * 40)
    assert git.available is False
    assert git.commit("paper/results/wer-toy.json") == "f" * 40
    assert git.commit("paper/results/other.json") == ""
    assert git.revision(["paper/results/wer-toy.json"]) == "e" * 40


def test_the_argv_is_copied_when_present_and_empty_otherwise(repo: Path) -> None:
    results = repo / "paper" / "results"
    prov = dict(PROV, argv="paper/benchmark/bench_wer.py 10 toy")
    _write_json(results / "wer-toy.json", WER_DOC, prov=prov)
    rows = _rows(_build(repo), "asr_librispeech_wer")
    assert {r["argv"] for r in rows} == {"paper/benchmark/bench_wer.py 10 toy"}
    assert {r["argv"] for r in _rows(_build(repo), "beam_sweep")} == {""}


def test_corpus_block_is_copied_and_validated_when_present(repo: Path) -> None:
    results = repo / "paper" / "results"
    corpus = {"dataset": "Toy", "n": 10, "stratified": True, "sha256_16": "0123456789abcdef"}
    _write_json(results / "wer-toy.json", WER_DOC, prov=dict(PROV, corpus=corpus))
    row = _rows(_build(repo), "asr_librispeech_wer")[0]
    assert (row["corpus_name"], row["corpus_n"], row["corpus_sha256_16"],
            row["corpus_stratified"]) == ("Toy", "10", "0123456789abcdef", "true")
    broken = {k: v for k, v in corpus.items() if k != "sha256_16"}
    _write_json(results / "wer-toy.json", WER_DOC, prov=dict(PROV, corpus=broken))
    with pytest.raises(X.ExportError, match=r"wer-toy\.json.*sha256_16"):
        _build(repo)


@pytest.mark.parametrize("field", ["timestamp", "cpu_model", "yazses", "os", "logical_cpus"])
def test_missing_required_provenance_names_file_and_field(repo: Path, field: str) -> None:
    _write_json(repo / "paper" / "results" / "wer-toy.json", WER_DOC, drop=(field,))
    with pytest.raises(X.ExportError, match=rf"wer-toy\.json.*{field}"):
        _build(repo)


def test_missing_provenance_block_is_an_error(repo: Path) -> None:
    (repo / "paper" / "results" / "wer-toy.json").write_text(
        '{"config": {}, "models": {"a": {"wer": 1.0}}}', encoding="utf-8")
    with pytest.raises(X.ExportError, match=r"wer-toy\.json.*provenance"):
        _build(repo)


@pytest.mark.parametrize(("text", "needle"), [
    ('{"config": {}, "models": []}', "models"),
    ('{"config": {}, "models": {"a": {"wer": "5%"}}}', "wer"),
    ('{"config": {}, "models": {"a": {"mer": 5.0}}}', "wer"),
    ('{"config": {}}', "models"),
    ('[1, 2]', "top-level"),
    ('{not json', "not valid JSON"),
    ('{"config": {}, "models": {"a": {"wer": 1.0, "wer_ci95": [1.0]}}}', "wer_ci95"),
])
def test_malformed_records_are_flagged_with_file_and_field(repo: Path, text: str, needle: str) -> None:
    results = repo / "paper" / "results"
    body = text
    if body.startswith("{") and "provenance" not in body and "not json" not in body:
        doc = json.loads(body, parse_float=Decimal)
        doc["provenance"] = dict(PROV)
        body = json.dumps(doc, default=float)
    (results / "wer-toy.json").write_text(body, encoding="utf-8")
    with pytest.raises(X.ExportError) as err:
        _build(repo)
    assert "wer-toy.json" in str(err.value)
    assert needle in str(err.value)


def test_unknown_parser_or_table_in_the_allowlist_is_rejected(repo: Path) -> None:
    with pytest.raises(X.ExportError, match="unknown parser"):
        X.build_export(repo, (X.Source("wer-toy.json", "asr_librispeech_wer", "nope"),),
                       git=FakeGit())
    with pytest.raises(X.ExportError, match="unknown table"):
        X.build_export(repo, (X.Source("wer-toy.json", "no_such_table", "wer"),), git=FakeGit())
    with pytest.raises(ValueError, match="unknown record kind"):
        X.Source("wer-toy.json", "asr_librispeech_wer", "wer", kind="guess")


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


_orig_build = X.build_export


def _run(argv: list[str], repo: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = X.main(argv + ["--root", str(repo)], out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_cli_modes_are_mutually_exclusive_and_required(repo: Path) -> None:
    with pytest.raises(SystemExit):
        X.main(["--root", str(repo)])
    with pytest.raises(SystemExit):
        X.main(["--check", "--write", "--root", str(repo)])


def test_cli_list_reports_included_and_excluded_without_writing(repo: Path) -> None:
    code, out, _ = _run(["--list"], repo)
    assert code == 0
    assert "INCLUDED" in out and "EXCLUDED" in out
    assert not (repo / X.OUT_REL).exists()


def test_cli_check_never_writes_and_exits_1_on_drift(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(X, "ALLOWLIST", TOY_SOURCES)
    monkeypatch.setattr(X, "build_export",
                        lambda root=X.REPO_ROOT, sources=TOY_SOURCES, git=None:
                        _orig_build(root, sources, FakeGit()))
    # nothing committed yet: drift (missing files), and --check must not create them
    code, _, err = _run(["--check"], repo)
    assert code == 1 and "missing" in err
    assert not (repo / X.OUT_REL).exists()
    assert _run(["--write"], repo)[0] == 0
    assert _run(["--check"], repo)[0] == 0
    target = repo / X.OUT_REL / "beam_sweep.csv"
    target.write_bytes(target.read_bytes() + b"tampered\n")
    tampered = target.read_bytes()
    code, _, err = _run(["--check"], repo)
    assert code == 1 and "changed" in err and "beam_sweep.csv" in err
    assert target.read_bytes() == tampered, "--check must never repair the drift it reports"
    (repo / X.OUT_REL / "extra.csv").write_text("x\n", encoding="utf-8")
    assert "unexpected" in _run(["--check"], repo)[2]


def test_cli_reports_a_sensitive_source_as_an_error_exit(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(X, "ALLOWLIST", TOY_SOURCES)
    monkeypatch.setattr(X, "build_export",
                        lambda root=X.REPO_ROOT, sources=TOY_SOURCES, git=None:
                        _orig_build(root, sources, FakeGit()))
    doc = json.loads(WER_DOC, parse_float=Decimal)
    doc["config"]["selection"] = "x " + _FAKE_SECRETS["e-mail"]
    doc["provenance"] = dict(PROV)
    (repo / "paper" / "results" / "wer-toy.json").write_text(
        json.dumps(doc, default=float), encoding="utf-8")
    code, _, err = _run(["--write"], repo)
    assert code == 2 and "wer-toy.json" in err and "e-mail" in err


def test_sha256sums_verifies_every_other_file(repo: Path) -> None:
    export = _build(repo)
    listed = {}
    for line in export.files[X.SUMS_NAME].decode().splitlines():
        digest, name = line.split("  ")
        listed[name] = digest
    assert set(listed) == set(export.files) - {X.SUMS_NAME}
    for name, digest in listed.items():
        assert hashlib.sha256(export.files[name]).hexdigest() == digest


# --------------------------------------------------------------------------------------
# The committed export, against the real archive
# --------------------------------------------------------------------------------------


def _csv(name: str) -> list[dict[str, str]]:
    with (DATA / f"{name}.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _src(rel: str):
    return json.loads((RESULTS / rel).read_text(encoding="utf-8"), parse_float=Decimal)


def _same(cell: str, source) -> bool:
    return Decimal(cell) == Decimal(str(source))


def test_the_committed_export_is_current() -> None:
    """The same check CI runs: regenerate in memory, compare bytes, never write."""
    out = io.StringIO()
    err = io.StringIO()
    code = X.main(["--check"], out=out, err=err)
    assert code == 0, err.getvalue()


def test_every_archive_file_is_accounted_for_in_the_committed_metadata() -> None:
    meta = json.loads((DATA / X.METADATA_NAME).read_text(encoding="utf-8"))
    archive = {f"paper/results/{p}" for p in X.list_archive(RESULTS)}
    included = {s["path"] for s in meta["sources"]}
    excluded = {e["path"] for e in meta["excluded"]}
    assert included | excluded == archive, (
        f"unaccounted: {sorted(archive - included - excluded)}; "
        f"stale: {sorted((included | excluded) - archive)}")
    assert not included & excluded
    assert included == {f"paper/results/{s.path}" for s in X.ALLOWLIST}
    for entry in meta["excluded"]:
        assert entry["reason"].strip()
        assert "not reviewed" not in entry["reason"], (
            f"{entry['path']} has no exclusion rule; decide whether to export it")


def test_committed_files_match_the_checksum_list_and_metadata_counts() -> None:
    meta = json.loads((DATA / X.METADATA_NAME).read_text(encoding="utf-8"))
    for line in (DATA / X.SUMS_NAME).read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == digest, name
    for table, info in meta["tables"].items():
        assert len(_csv(table)) == info["rows"] == meta["row_counts"][table]
    assert {p.stem for p in DATA.glob("*.csv")} == set(meta["tables"])


def test_every_exported_source_row_count_matches_its_source() -> None:
    assert len(_csv("asr_librispeech_wer")) == len(_src("wer.json")["models"]) + len(
        _src("wer-test-other.json")["models"])
    beams = sum(len(_src(f)["rows"]) for f in (
        "beam-test-clean.json", "beam-test-other.json", "beam-governor-test-clean.json",
        "beam-governor-test-other.json"))
    assert len(_csv("beam_sweep")) == beams
    comps = sum(len(_src(p.name)["comparisons"]) for p in RESULTS.glob("beam-*-significance*.json"))
    assert len(_csv("significance_beam")) == comps
    assert len(_csv("significance_onset")) == len(_src("onset-significance.json")["comparisons"])
    assert len(_csv("persian_asr")) == len(list(RESULTS.glob("persian-*.json")))
    assert len(_csv("diarization_recordings")) == sum(
        len(_src(f)["meetings"]) for f in
        ("diarization-ami16_corpus-der.json", "diarization-ami16_corpus-maxspk4.json"))


def test_wer_values_equal_the_source_json() -> None:
    rows = {(r["source_file"], r["model_key"]): r for r in _csv("asr_librispeech_wer")}
    for fname in ("wer.json", "wer-test-other.json"):
        for key, m in _src(fname)["models"].items():
            row = rows[(f"paper/results/{fname}", key)]
            for col, field in (("wer_pct", "wer"), ("mer_pct", "mer"), ("rtf_mean", "rtf_mean"),
                               ("rtf_p95", "rtf_p95"), ("substitutions", "substitutions"),
                               ("decode_seconds_total", "decode_seconds_total")):
                assert _same(row[col], m[field]), (fname, key, col)
    base = rows[("paper/results/wer.json", "base.en")]
    assert base["wer_pct"] == "4.07" and base["machine_cpu_model"].startswith("13th Gen Intel")
    assert base["engine"] == ""  # the 2.12 file predates the field: empty, not inferred


def test_beam_values_and_ci_equal_the_source_json() -> None:
    src = _src("beam-test-clean.json")
    rows = [r for r in _csv("beam_sweep") if r["source_file"].endswith("/beam-test-clean.json")]
    assert len(rows) == len(src["rows"])
    for row, s in zip(rows, src["rows"], strict=True):
        assert row["model"] == s["model"] and _same(row["beam_size"], s["beam_size"])
        assert _same(row["wer_pct"], s["wer_pct"]) and _same(row["rtf"], s["rtf"])
        assert _same(row["wer_ci95_low_pct"], s["wer_ci95"][0])
        assert _same(row["wer_ci95_high_pct"], s["wer_ci95"][1])
        assert row["experiment"] == "beam-test" and row["corpus_split"] == "test-clean"
    assert "per_utt_errors" not in (DATA / "beam_sweep.csv").read_text(encoding="utf-8")


def test_beam_governor_is_not_merged_into_the_default_model_sweep() -> None:
    by_exp: dict[str, set[str]] = {}
    for r in _csv("beam_sweep"):
        by_exp.setdefault(r["experiment"], set()).add(r["model"])
    assert set(by_exp) == {"beam-test", "beam-governor"}
    # the governor grid never scores the default model, which is why the two must stay apart
    assert "base.en" not in by_exp["beam-governor"] and "tiny.en" in by_exp["beam-governor"]


def test_latency_and_streaming_values_equal_the_source_json() -> None:
    lat = _src("latency.json")
    rows = {r["model"]: r for r in _csv("latency_decode")}
    for model, m in lat["models"].items():
        assert _same(rows[model]["decode_median_ms"], m["decode_median_ms"])
        assert _same(rows[model]["rss_peak_mb"], m["rss_peak_mb"])
    stages = {r["stage"]: r for r in _csv("latency_pipeline_stages")}
    assert _same(stages["vad_gate"]["p95_ms"], lat["pipeline_stages"]["vad_gate"]["p95_ms"])
    st = _src("streaming.json")["models"]["tiny.en"]
    srow = {r["model"]: r for r in _csv("streaming_latency")}["tiny.en"]
    assert _same(srow["streaming_speech_end_to_final_s_p95"],
                 st["streaming_speech_end_to_final_s"]["p95"])


def test_persian_values_equal_the_source_json() -> None:
    rows = {r["source_file"].rsplit("/", 1)[1]: r for r in _csv("persian_asr")}
    for path in sorted(RESULTS.glob("persian-*.json")):
        src = _src(path.name)
        row = rows[path.name]
        m = src["metrics"]
        assert _same(row["wer_normalized_pct"], m["wer_normalized"]), path.name
        assert _same(row["cer_normalized_pct"], m["cer_normalized"]), path.name
        assert _same(row["rtf"], m["rtf"]), path.name
        assert row["corpus_name"] == src["corpus"]["name"]
        assert _same(row["corpus_n"], src["corpus"]["samples"])
        assert row["argv"] == src["provenance"]["argv"]
    # the cvfa fine-tune row: ZWNJ is vacuous there (no reference joiners) and published as such
    steja = rows["persian-cvfa-test10559-steja-small.json"]
    assert steja["zwnj_reference_count"] == "0" and steja["zwnj_recall"] == "1.0"


def test_diarization_values_and_post_hoc_fields_are_labelled() -> None:
    src = _src("diarization-ami16_corpus-der.json")
    by_id = {r["recording_id"]: r for r in _csv("diarization_recordings")
             if r["source_file"].endswith("-der.json")}
    for m in src["meetings"]:
        row = by_id[m["id"]]
        assert _same(row["strict_der_pct"], m["strict"]["der"])
        assert _same(row["collar250ms_der_pct"], m["collar250ms"]["der"])
        assert _same(row["strict_scored_seconds"], m["strict"]["scored_seconds"])
    summary = {r["source_file"].rsplit("/", 1)[1]: r for r in _csv("diarization_corpus_summary")}
    der = summary["diarization-ami16_corpus-der.json"]
    assert _same(der["strict_der_mean_pct"], src["summary"]["der_strict"])
    assert _same(der["strict_der_time_weighted_pct"], src["summary"]["der_strict_time_weighted"])
    assert "der_strict_time_weighted" in der["derived_after_run_fields"]
    assert der["max_speakers"] == "0" and summary[
        "diarization-ami16_corpus-maxspk4.json"]["max_speakers"] == "4"


def test_significance_values_equal_the_source_json() -> None:
    src = _src("beam-test-clean-significance.json")
    rows = [r for r in _csv("significance_beam")
            if r["source_file"].endswith("/beam-test-clean-significance.json")]
    for row, c in zip(rows, src["comparisons"], strict=True):
        assert row["comparison_a"] == c["a"] and row["comparison_b"] == c["b"]
        assert _same(row["p_value"], c["p"]) and _same(row["diff_a_minus_b_pct"], c["diff"])
        assert row["analysis_of"] == "beam-test-clean.json"
        assert row["baseline_beam"] == ""  # the default-baseline files do not record one
    vs2 = [r for r in _csv("significance_beam") if r["source_file"].endswith("vs-beam2.json")]
    assert vs2 and {r["baseline_beam"] for r in vs2} == {"2"}
    onset = _src("onset-significance.json")
    orow = _csv("significance_onset")[0]
    c0 = onset["comparisons"][0]
    assert _same(orow["p_value"], c0["p"]) and _same(orow["discordant"], c0["discordant"])
    diar = _src("diarization-ami16_corpus-maxspk4-vs-der-significance.json")["result"]["strict"]
    drow = {r["collar"]: r for r in _csv("significance_diarization")}["strict"]
    assert _same(drow["sign_test_p"], diar["sign_test_p"])
    assert json.loads(drow["per_meeting_delta_json"], parse_float=Decimal) == diar["per_meeting_delta"]


def test_command_and_vad_values_equal_the_source_json() -> None:
    cmd = _src("commands.json")
    row = _csv("command_grammar")[0]
    assert _same(row["action_accuracy_pct"], cmd["precision"]["action_accuracy_pct"])
    assert _same(row["n_command_phrases"], cmd["config"]["n_command_phrases"])
    assert row["false_positive_count"] == str(len(cmd["false_positive"]["false_positives"]))
    vad = _src("vad.json")
    assert _same(_csv("vad_gate")[0]["balanced_accuracy_pct"],
                 vad["results"]["balanced_accuracy_pct"])


def test_onset_values_equal_the_source_json() -> None:
    src = _src("onset.json")
    rows = _csv("onset_first_word")
    assert len(rows) == len(src["rows"])
    for row, s in zip(rows, src["rows"], strict=True):
        assert row["arm"] == s["arm"] and _same(row["first_word_ok"], s["first_word_ok"])
        assert _same(row["wer_pct"], s["wer_pct"])
    assert "first_word_hits" not in (DATA / "onset_first_word.csv").read_text(encoding="utf-8")


def test_no_exported_cell_is_a_manufactured_zero_for_a_missing_source_value() -> None:
    """`platform`-style gaps (a pre-2.2x file with no ci, no engine) must stay empty."""
    old = [r for r in _csv("asr_librispeech_wer") if r["source_file"].endswith("/wer.json")]
    assert old
    for r in old:
        assert r["wer_ci95_low_pct"] == "" and r["wer_ci95_high_pct"] == ""
        assert r["n_scored_utterances"] == ""
    for table in X.TABLES:
        for r in _csv(table):
            assert r["corpus_sha256_16"] == "" and r["corpus_stratified"] == "", (
                "no archived file records a corpus digest/stratification flag yet; "
                "if one does, update this test with the value")


def test_each_table_declares_one_record_kind_and_rows_agree() -> None:
    for table in X.TABLES:
        kinds = {r["record_kind"] for r in _csv(table)}
        assert kinds == {X.TABLE_KIND[table]}, table


# --------------------------------------------------------------------------------------
# The dataset card
# --------------------------------------------------------------------------------------


def _front_matter() -> dict:
    yaml = pytest.importorskip("yaml")
    text = CARD.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    return yaml.safe_load(text.split("---\n", 2)[1])


def test_the_card_lists_every_csv_as_its_own_config() -> None:
    fm = _front_matter()
    configs = {c["config_name"]: c["data_files"] for c in fm["configs"]}
    assert configs == {p.stem: f"data/{p.name}" for p in sorted(DATA.glob("*.csv"))}
    for key in ("pretty_name", "license", "task_categories", "tags", "size_categories"):
        assert fm.get(key), key
    assert "automatic-speech-recognition" in fm["task_categories"]


def test_the_card_states_its_revision_row_counts_and_date_range() -> None:
    text = CARD.read_text(encoding="utf-8")
    meta = json.loads((DATA / X.METADATA_NAME).read_text(encoding="utf-8"))
    assert meta["source_revision"] and meta["source_revision"] in text, (
        "README.md names a stale source revision; update it from export-metadata.json")
    for table, rows in meta["row_counts"].items():
        assert re.search(rf"`{table}`[^\n]*\|\s*{rows}\s*\|", text), (table, rows)
    stamps = sorted(r["timestamp_utc"] for t in meta["tables"] for r in _csv(t))
    assert stamps[0][:10] in text and stamps[-1][:10] in text


def test_the_card_carries_the_mandatory_statements() -> None:
    text = CARD.read_text(encoding="utf-8")
    low = text.lower()
    assert "no audio" in low and "no user voice recordings" in low
    assert "same `machine`" in text, "the latency/RTF comparability warning is missing"
    assert "OWNER-DECISION" not in text, "internal decision notes belong in the report, not the card"
    assert "2607.28878" in text
    assert "significance_analysis" in text
