"""FA-05: the HF -> CT2 conversion tool's contract.

`paper/benchmark/convert_hf_to_ct2.py` turns fine-tune checkpoints the Hub does
not ship as CT2 into directories faster-whisper can measure, and writes a
`conversion.json` sidecar — because #514's own rule is that a converted model's
number is only worth archiving when the conversion procedure is pinned with it.

These tests are deliberately **stdlib-only**: the module imports nothing but the
standard library, and the torch/transformers/ctranslate2 work runs in a separate
interpreter passed by `--python`. That is the design's whole point — the contract
that carries the risk (which files get fetched, what refuses to overwrite, what
the sidecar promises) is testable in the CI harness job without 200 MB of torch.
The conversion call itself is exercised for real in the FA-05 run, never here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.benchmark_deps import load

BENCH = Path(__file__).resolve().parents[1] / "paper" / "benchmark"


@pytest.fixture(scope="module")
def conv():
    return load("convert_hf_to_ct2", "convert_hf_to_ct2.py")


# ── the fetch allowlist: the 6.5 GB checkpoint incident, pinned ───────────────


def test_root_files_selects_exact_root_names_only(conv):
    listing = [
        "config.json",
        "pytorch_model.bin",
        "checkpoint-2500/pytorch_model.bin",  # a partial-training checkpoint
        "checkpoint-1000/config.json",
        "nested/dir/vocab.json",
        ".gitattributes",
        "README.md",
    ]
    assert conv.root_files(listing) == ["config.json", "pytorch_model.bin"]


def test_root_files_deduplicates_and_sorts(conv):
    assert conv.root_files(
        ["vocab.json", "config.json", "config.json"]
    ) == ["config.json", "vocab.json"]


def test_safetensors_checkpoints_are_recognized_too(conv):
    assert "model.safetensors" in conv.root_files(["model.safetensors"])
    assert "weights.bin" in conv.root_files(["weights.bin"])


def test_the_real_steja_listing_yields_the_nine_files(conv):
    """Pinned against the actual tree listing of the first FA-05 candidate.

    If the repo's layout changes, this test fails and the allowlist gets a
    decision made about it — not a silent fetch of whatever appeared.
    """
    listing = [
        ".gitattributes", ".gitignore", "README.md", "added_tokens.json",
        "all_results.json", "config.json", "eval_results.json", "merges.txt",
        "normalizer.json", "preprocessor_config.json", "pytorch_model.bin",
        "special_tokens_map.json", "tokenizer_config.json", "train_results.json",
        "trainer_state.json", "training_args.bin", "vocab.json",
    ] + [f"checkpoint-{n}/pytorch_model.bin" for n in (500, 1000, 1500, 2000,
                                                       2500, 3000, 3500, 4000, 4500)]
    assert conv.root_files(listing) == [
        "added_tokens.json",
        "config.json",
        "merges.txt",
        "normalizer.json",
        "preprocessor_config.json",
        "pytorch_model.bin",
        "special_tokens_map.json",
        "tokenizer_config.json",
        "vocab.json",
    ]


# ── refusal rules: an archive-corrupting mistake is worse than a failed run ───


def test_refuses_a_nonempty_output_directory(conv, tmp_path):
    out = tmp_path / "ct2"
    out.mkdir()
    (out / "model.bin").write_bytes(b"x")
    with pytest.raises(SystemExit, match="non-empty"):
        conv.convert("steja/whisper-small-persian", "8c600b6b" + "69" * 30,
                     out, python=sys.executable)


def test_refuses_a_repo_without_a_root_config(conv, monkeypatch):
    monkeypatch.setattr(conv, "_remote_listing", lambda *a, **k: ["README.md"])
    with pytest.raises(SystemExit, match="not a convertible"):
        conv.convert("some/repo", "0" * 40, _empty_dir(), python=sys.executable)


def _empty_dir():
    import tempfile

    return Path(tempfile.mkdtemp())


# ── the sidecar: what makes a converted model auditable ───────────────────────


def test_sidecar_records_source_tools_command_and_digests(conv, tmp_path, monkeypatch):
    """A dry run with the converter replaced by a stub that drops real files.

    The stub mimics only what the sidecar must describe: output files exist
    after a successful pass, and `conversion.json` lands inside the directory.
    """
    import hashlib

    out = tmp_path / "ct2"
    out.mkdir()

    def fake_listing(repo, revision, python):
        return ["config.json", "pytorch_model.bin", "README.md"]

    def fake_run(cmd, capture_output, text):
        (out / "model.bin").write_bytes(b"weights")
        (out / "config.json").write_text("{}")

        class R:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return R()

    monkeypatch.setattr(conv, "_remote_listing", fake_listing)
    monkeypatch.setattr(conv.subprocess, "run", fake_run)
    monkeypatch.setattr(
        conv, "_tool_versions",
        lambda p: {"ctranslate2": "4.8.1", "torch": "2.x"},
    )

    sidecar = conv.convert("steja/whisper-small-persian", "8c" + "0" * 38,
                           out, python=sys.executable)

    assert sidecar["conversion_schema"] == conv.CONVERSION_SCHEMA_VERSION
    assert sidecar["source_repo"] == "steja/whisper-small-persian"
    assert sidecar["source_revision"] == "8c" + "0" * 38
    assert sidecar["root_files_fetched"] == ["config.json", "pytorch_model.bin"]
    assert sidecar["tools"]["ctranslate2"] == "4.8.1"
    assert "ctranslate2.converters.transformers" in sidecar["command"]
    # Every output file digested, sidecar excluded from its own digest map.
    assert set(sidecar["output_sha256"]) == {"model.bin", "config.json"}
    real = hashlib.sha256((out / "model.bin").read_bytes()).hexdigest()
    assert sidecar["output_sha256"]["model.bin"] == real
    # The sidecar is on disk, valid JSON, and self-consistent with the return.
    on_disk = json.loads((out / "conversion.json").read_text(encoding="utf-8"))
    assert on_disk == sidecar


def test_sidecar_is_deterministic_in_field_order(conv, tmp_path, monkeypatch):
    out = tmp_path / "ct2"
    out.mkdir()

    def fake_run(cmd, capture_output, text):
        (out / "model.bin").write_bytes(b"w")

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setattr(conv, "_remote_listing",
                        lambda *a: ["config.json", "pytorch_model.bin"])
    monkeypatch.setattr(conv.subprocess, "run", fake_run)
    monkeypatch.setattr(conv, "_tool_versions", lambda p: {})
    conv.convert("r/x", "0" * 40, out, python=sys.executable)
    text = (out / "conversion.json").read_text(encoding="utf-8")
    # Sorted keys and stable indent: a reader diffing two sidecars must see
    # semantic changes only, never key-order noise.
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"


def test_failed_conversion_raises_and_leaves_no_sidecar(conv, tmp_path, monkeypatch):
    out = tmp_path / "ct2"
    out.mkdir()

    def fake_run(cmd, capture_output, text):
        class R:
            returncode = 1
            stdout = ""
            stderr = "boom: cuda not found"

        return R()

    monkeypatch.setattr(conv, "_remote_listing",
                        lambda *a: ["config.json", "pytorch_model.bin"])
    monkeypatch.setattr(conv.subprocess, "run", fake_run)
    with pytest.raises(SystemExit, match="conversion failed"):
        conv.convert("r/x", "0" * 40, out, python=sys.executable)
    assert not (out / "conversion.json").exists()
