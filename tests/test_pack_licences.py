"""scripts/pack_licences.py -- the ADR-028 Q7 build-time licence gate for add-on packs.

Offline and synthetic: every distribution here is a hand-written METADATA file, never a
real wheel. The pure classifier is tested rule by rule; ``check_pack`` is tested on
dist-info directories written to ``tmp_path``; and the wiring into
``scripts/build-packs.py`` is tested end to end with the same fakes
``tests/test_build_packs.py`` uses, so a withheld pack is proven withheld and a
published one is proven acceptable to the runtime's own extractor.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

from tests.test_build_packs import _argv, _fake_bundle, _install_fake

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pack_licences.py"
BUILD = ROOT / "scripts" / "build-packs.py"
APPROVALS = ROOT / "packaging" / "packs" / "licence-approvals.toml"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pl():
    return _load("pack_licences", SCRIPT)


@pytest.fixture(scope="module")
def bp(pl):
    return _load("build_packs", BUILD)


# --- SPDX expressions ----------------------------------------------------------------


@pytest.mark.parametrize("expr, cls", [
    ("MIT", "permissive"),
    ("Apache-2.0", "permissive"),
    ("BSD-3-Clause", "permissive"),
    ("mit", "permissive"),                       # ids match without case
    ("LGPL-2.1", "LGPL"),
    ("LGPL-2.1-or-later", "LGPL"),
    ("MPL-2.0", "LGPL"),
    ("GPL-3.0-or-later", "GPL"),
    ("GPL-2.0+", "GPL"),
    ("AGPL-3.0-only", "GPL"),
    # OR: the recipient may choose, so the most permissive branch decides.
    ("MIT OR GPL-3.0", "permissive"),
    ("GPL-3.0 OR LGPL-2.1", "LGPL"),
    ("MIT or GPL-3.0", "permissive"),            # all-lower-case operators are SPDX
    ("MIT OR Some-Unknown-1.0", "permissive"),
    # AND: every part applies, so the strictest decides.
    ("MIT AND GPL-3.0-only", "GPL"),
    ("MIT AND LGPL-2.1", "LGPL"),
    ("MIT AND Some-Unknown-1.0", "UNKNOWN"),
    ("(MIT OR LGPL-2.1) AND GPL-3.0", "GPL"),
    ("MIT AND (GPL-3.0 OR BSD-2-Clause)", "permissive"),
    # WITH only relaxes, and only with an exception the gate knows.
    ("GPL-2.0-or-later WITH Classpath-exception-2.0", "LGPL"),
    ("GPL-3.0 WITH GCC-exception-3.1", "LGPL"),
    ("Apache-2.0 WITH LLVM-exception", "permissive"),
    ("GPL-3.0 WITH Made-Up-exception", "UNKNOWN"),
    ("MIT WITH Made-Up-exception", "UNKNOWN"),
    # Anything not certain is UNKNOWN.
    ("LicenseRef-Proprietary", "UNKNOWN"),
    ("Some-Unknown-1.0", "UNKNOWN"),
    ("", "UNKNOWN"),
    ("MIT OR", "UNKNOWN"),
    ("(MIT", "UNKNOWN"),
    ("MIT)", "UNKNOWN"),
    ("MIT Or GPL-3.0", "UNKNOWN"),               # mixed-case operator is not SPDX
    ("MIT GPL-3.0", "UNKNOWN"),
    ("MIT; GPL", "UNKNOWN"),
    ("MIT\nGPL-3.0", "UNKNOWN"),
])
def test_spdx_expressions(pl, expr, cls):
    assert pl.classify_spdx(expr) == cls


# --- metadata -> class ---------------------------------------------------------------


def _meta(pl, text):
    return pl.parse_metadata("Metadata-Version: 2.4\nName: x\nVersion: 1.0\n" + text + "\n")


@pytest.mark.parametrize("headers, cls, basis", [
    ("License-Expression: MIT", "permissive", "License-Expression"),
    ("License-Expression: Apache-2.0", "permissive", "License-Expression"),
    ("License-Expression: BSD-3-Clause", "permissive", "License-Expression"),
    ("License-Expression: MIT OR GPL-3.0", "permissive", "License-Expression"),
    ("License-Expression: GPL-3.0-or-later", "GPL", "License-Expression"),
    ("License-Expression: LGPL-2.1", "LGPL", "License-Expression"),
    # The expression is authoritative: a stray classifier does not override it.
    ("License-Expression: MIT\nClassifier: License :: OSI Approved :: GNU General "
     "Public License v3 (GPLv3)", "permissive", "License-Expression"),
    ("License: MIT", "permissive", "License"),
    ("License: Apache 2.0", "permissive", "License"),
    ("License: BSD-3-Clause", "permissive", "License"),
    # Classifier only.
    ("Classifier: License :: OSI Approved :: BSD License", "permissive", "classifiers"),
    ("Classifier: License :: OSI Approved :: GNU Lesser General Public License v2 or "
     "later (LGPLv2+)", "LGPL", "classifiers"),
    ("Classifier: License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
     "GPL", "classifiers"),
    ("Classifier: License :: OSI Approved :: MIT License\nClassifier: License :: OSI "
     "Approved :: GNU General Public License v2 (GPLv2)", "GPL", "classifiers"),
    ("Classifier: License :: Other/Proprietary License", "UNKNOWN", "classifiers"),
    ("Classifier: License :: OSI Approved", "UNKNOWN", "classifiers"),
    # Free text falls through to the classifiers, or is UNKNOWN without one.
    ("License: Apache licensed, as found in the LICENSE file", "UNKNOWN",
     "License (free text, not an SPDX expression)"),
    ("License: see LICENSE\nClassifier: License :: OSI Approved :: MIT License",
     "permissive", "classifiers"),
    # A continued License header is free text, not its first line.
    ("License: MIT\n        except the vendored codec, which is GPL-2.0", "UNKNOWN",
     "License (free text, not an SPDX expression)"),
    # Legacy field and classifier disagree: the stricter wins.
    ("License: MIT\nClassifier: License :: OSI Approved :: GNU General Public License "
     "(GPL)", "GPL", "License + classifiers"),
    # No licence at all.
    ("", "UNKNOWN", "none"),
    ("License: UNKNOWN", "UNKNOWN", "none"),
    ("Classifier: Programming Language :: Python :: 3", "UNKNOWN", "none"),
])
def test_declared_licence(pl, headers, cls, basis):
    got_cls, _, got_basis = pl.declared_licence(_meta(pl, headers))
    assert (got_cls, got_basis) == (cls, basis)


def test_parse_metadata_stops_at_the_body_and_keeps_continuations(pl):
    meta = pl.parse_metadata(
        "Name: a\nLicense: line one\n  line two\nClassifier: A\nClassifier: B\n\n"
        "License: in the body, ignored\n")
    assert meta["License"] == ["line one\nline two"]
    assert meta["Classifier"] == ["A", "B"]


def test_source_url_prefers_the_source_label_then_home_page(pl):
    meta = {"Project-URL": ["Documentation, https://docs.example/",
                            "Homepage, https://example.org/",
                            "Source Code, https://git.example/x"],
            "Home-page": ["https://legacy.example/"]}
    assert pl.source_url(meta) == "https://git.example/x"
    assert pl.source_url({"Project-URL": ["Homepage, https://example.org/"]}) == (
        "https://example.org/")
    assert pl.source_url({"Home-page": ["https://legacy.example/"]}) == (
        "https://legacy.example/")
    assert pl.source_url({"Project-URL": ["Source, not a url"], "Home-page": ["UNKNOWN"]}) is None


def test_licence_files_are_licence_texts_only(pl):
    assert pl.is_licence_file("LICENSE")
    assert pl.is_licence_file("LICENCE.txt")
    assert pl.is_licence_file("COPYING")
    assert pl.is_licence_file("licenses/LICENSE.md")
    assert not pl.is_licence_file("NOTICE")
    assert not pl.is_licence_file("AUTHORS")
    assert not pl.is_licence_file("METADATA")


# --- check_pack on synthetic dist-info directories -------------------------------------


def _dist(site: Path, name: str, version: str, headers: str, *, licence_file: bool = True,
          url: str | None = "https://example.org/src") -> Path:
    di = site / f"{name.replace('-', '_')}-{version}.dist-info"
    di.mkdir(parents=True)
    body = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n{headers}\n"
    if url:
        body += f"Project-URL: Source, {url}\n"
    (di / "METADATA").write_text(body + "\nLong description.\n", encoding="utf-8")
    if licence_file:
        (di / "licenses").mkdir()
        (di / "licenses" / "LICENSE").write_text("licence text\n", encoding="utf-8")
    return di


def _approvals(tmp_path: Path, body: str = "") -> Path:
    path = tmp_path / "licence-approvals.toml"
    path.write_text("format = 1\n" + body, encoding="utf-8")
    return path


def _approval(pack="prosody", dist="gpl-thing", version="1.0", licence="GPL-3.0-or-later",
              table="approval", by_key="approved_by"):
    return (f'\n[[{table}]]\npack = "{pack}"\ndist = "{dist}"\nversion = "{version}"\n'
            f'licence = "{licence}"\n{by_key} = "A. Owner"\ndate = "2026-10-21"\n'
            f'reason = "recorded for the test"\n')


def test_permissive_packs_pass_without_a_source_offer(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "mit-thing", "1.0", "License-Expression: MIT"),
           _dist(site, "apache-thing", "2.0", "License-Expression: Apache-2.0"),
           _dist(site, "bsd-thing", "3.0", "License-Expression: BSD-3-Clause"),
           _dist(site, "dual", "4.0", "License-Expression: MIT OR GPL-3.0"),
           _dist(site, "classifier-only", "5.0",
                 "Classifier: License :: OSI Approved :: MIT License")]
    v = pl.check_pack("parakeet", dis, _approvals(tmp_path))
    assert v.ok, v.problems
    assert {d.licence_class for d in v.dists} == {"permissive"}
    assert v.source_md is None
    assert v.report()["source_offer"] is None


def test_a_missing_licence_file_fails_even_a_permissive_dist(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "sherpa-onnx-core", "1.13.8", "License: Apache-2.0",
                 licence_file=False)]
    v = pl.check_pack("diarization", dis, _approvals(tmp_path))
    assert not v.ok
    assert v.problems == ["sherpa-onnx-core 1.13.8: no licence file in its dist-info"]


def test_no_licence_at_all_fails(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "espeakng-loader", "0.2.4", "", licence_file=False)]
    v = pl.check_pack("tts", dis, _approvals(tmp_path))
    assert not v.ok
    assert len(v.problems) == 2
    assert any("no licence file" in p for p in v.problems)
    assert any("not classifiable" in p and "(not declared)" in p for p in v.problems)


def test_free_text_licence_fails_until_someone_clarifies_it(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "sherpa-onnx", "1.13.8",
                 "License: Apache licensed, as found in the LICENSE file")]
    assert not pl.check_pack("diarization", dis, _approvals(tmp_path)).ok
    clar = _approval(pack="diarization", dist="sherpa_onnx", version="1.13.8",
                     licence="Apache-2.0", table="clarification", by_key="reviewed_by")
    v = pl.check_pack("diarization", dis, _approvals(tmp_path, clar))
    assert v.ok, v.problems
    assert v.dists[0].licence == "Apache-2.0"
    assert v.dists[0].basis.startswith("clarification by A. Owner")


def test_a_clarification_never_excuses_a_missing_licence_file(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "core", "1.0", "License: whatever", licence_file=False)]
    clar = _approval(pack="p", dist="core", version="1.0", licence="MIT",
                     table="clarification", by_key="reviewed_by")
    v = pl.check_pack("p", dis, _approvals(tmp_path, clar))
    assert v.problems == ["core 1.0: no licence file in its dist-info"]


def test_a_clarification_to_gpl_still_needs_an_approval(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "g", "1.0", "License: see COPYING")]
    clar = _approval(pack="p", dist="g", licence="GPL-3.0-only", table="clarification",
                     by_key="reviewed_by")
    v = pl.check_pack("p", dis, _approvals(tmp_path, clar))
    assert not v.ok and "recorded owner approval" in v.problems[0]
    both = clar + _approval(pack="p", dist="g", licence="GPL-3.0-only")
    assert pl.check_pack("p", dis, _approvals(tmp_path, both)).ok


def test_lgpl_passes_with_a_generated_source_offer(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "lgpl-thing", "2.1.0", "License-Expression: LGPL-2.1",
                 url="https://git.example/lgpl-thing"),
           _dist(site, "mit-thing", "1.0", "License-Expression: MIT")]
    v = pl.check_pack("p", dis, _approvals(tmp_path))
    assert v.ok, v.problems
    assert v.report()["source_offer"] == "LICENSES/SOURCE.md"
    md = v.source_md
    assert "| lgpl-thing | 2.1.0 | LGPL-2.1 (LGPL) | https://git.example/lgpl-thing |" in md
    assert "https://pypi.org/project/lgpl-thing/2.1.0/" in md
    assert "mit-thing" not in md, "the offer lists copyleft components only"


def test_lgpl_without_an_upstream_url_fails(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "lgpl-thing", "2.1.0", "License-Expression: LGPL-2.1", url=None)]
    v = pl.check_pack("p", dis, _approvals(tmp_path))
    assert not v.ok and "no upstream source URL" in v.problems[0]


def test_gpl_fails_without_a_recorded_approval(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "gpl-thing", "1.0", "License-Expression: GPL-3.0-or-later")]
    v = pl.check_pack("prosody", dis, _approvals(tmp_path))
    assert not v.ok
    assert "needs a recorded owner approval for pack 'prosody'" in v.problems[0]


def test_gpl_passes_with_a_matching_approval_and_says_so_in_the_offer(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "gpl-thing", "1.0", "License-Expression: GPL-3.0-or-later")]
    v = pl.check_pack("prosody", dis, _approvals(tmp_path, _approval()))
    assert v.ok, v.problems
    assert v.stale == []
    assert v.dists[0].approved_by == "A. Owner on 2026-10-21"
    assert "gpl-thing 1.0: approved by A. Owner on 2026-10-21" in v.source_md
    assert v.pack_json() == [{"name": "gpl-thing", "version": "1.0",
                              "licence": "GPL-3.0-or-later", "class": "GPL"}]


def test_an_approval_for_another_pack_does_not_approve(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "gpl-thing", "1.0", "License-Expression: GPL-3.0-or-later")]
    v = pl.check_pack("tts", dis, _approvals(tmp_path, _approval(pack="prosody")))
    assert not v.ok
    assert v.stale == [], "another pack's approval is not this pack's business"


@pytest.mark.parametrize("approval, why", [
    ({"version": "0.9"}, "the pack now has gpl-thing 1.0"),
    ({"licence": "GPL-2.0-only"}, "the licence is now 'GPL-3.0-or-later'"),
    ({"dist": "gone-thing"}, "gone-thing is not in pack 'prosody'"),
])
def test_a_stale_approval_is_reported_and_approves_nothing(pl, tmp_path, approval, why):
    site = tmp_path / "site"
    dis = [_dist(site, "gpl-thing", "1.0", "License-Expression: GPL-3.0-or-later")]
    v = pl.check_pack("prosody", dis, _approvals(tmp_path, _approval(**approval)))
    assert not v.ok, "a stale approval must not approve"
    assert len(v.stale) == 1 and why in v.stale[0], v.stale
    assert v.report()["stale_approvals"] == v.stale


def test_a_stale_clarification_is_reported_and_clarifies_nothing(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "sherpa-onnx", "1.13.9", "License: Apache licensed")]
    clar = _approval(pack="p", dist="sherpa-onnx", version="1.13.8", licence="Apache-2.0",
                     table="clarification", by_key="reviewed_by")
    v = pl.check_pack("p", dis, _approvals(tmp_path, clar))
    assert not v.ok
    assert "the pack now has sherpa-onnx 1.13.9" in v.stale[0]


def test_an_unneeded_approval_is_reported(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "gpl-thing", "1.0", "License-Expression: MIT")]
    v = pl.check_pack("prosody", dis, _approvals(tmp_path, _approval(licence="MIT")))
    assert v.ok
    assert "not needed, gpl-thing is permissive" in v.stale[0]


def test_a_malformed_entry_approves_nothing_and_is_reported(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "gpl-thing", "1.0", "License-Expression: GPL-3.0-or-later")]
    bad = _approval().replace('approved_by = "A. Owner"\n', "")
    v = pl.check_pack("prosody", dis, _approvals(tmp_path, bad))
    assert not v.ok
    assert any("ignored" in s and "approved_by" in s for s in v.stale)


@pytest.mark.parametrize("text", ["format = 2\n", "not toml at all [[[\n", None])
def test_an_unreadable_approvals_file_honours_nothing(pl, tmp_path, text):
    site = tmp_path / "site"
    dis = [_dist(site, "gpl-thing", "1.0", "License-Expression: GPL-3.0-or-later")]
    path = tmp_path / "approvals.toml"
    if text is not None:
        path.write_text(text + _approval(), encoding="utf-8")
    v = pl.check_pack("prosody", dis, path)
    assert not v.ok
    assert v.stale and all(s.startswith("ignored: ") for s in v.stale)


def test_a_toml_date_literal_is_accepted(pl, tmp_path):
    site = tmp_path / "site"
    dis = [_dist(site, "gpl-thing", "1.0", "License-Expression: GPL-3.0-or-later")]
    body = _approval().replace('date = "2026-10-21"', "date = 2026-10-21")
    assert pl.check_pack("prosody", dis, _approvals(tmp_path, body)).ok


def test_the_committed_approvals_file_parses_cleanly(pl):
    import tomllib

    parsed = pl.parse_approvals(tomllib.loads(APPROVALS.read_text(encoding="utf-8")))
    assert parsed.errors == []
    # Every recorded decision is a real one: nothing but the owner adds an approval.
    for rec in parsed.approvals + parsed.clarifications:
        assert "<" not in rec.by and "YYYY" not in rec.date


def test_the_gate_is_standard_library_only():
    """build-packs.py runs it on the Windows runner with nothing new installed."""
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    tops = {
        (n.module if isinstance(n, ast.ImportFrom) else a.name).split(".")[0]
        for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [n])
        if not (isinstance(n, ast.ImportFrom) and n.module == "__future__")
    }
    assert tops <= set(sys.stdlib_module_names), tops - set(sys.stdlib_module_names)


# --- wired into build-packs.py --------------------------------------------------------


def _rewrite_metadata(monkeypatch, bp, changes):
    """After the fake ``uv pip install``, replace named dists' METADATA / licence files."""
    inner = bp._run

    def run(cmd, **kw):
        out = inner(cmd, **kw)
        if cmd[:3] == ["uv", "pip", "install"]:
            target = Path(cmd[cmd.index("--target") + 1])
            for di in target.glob("*.dist-info"):
                name = di.name.split("-", 1)[0].replace("_", "-")
                if name not in changes:
                    continue
                headers, keep_licence = changes[name]
                (di / "METADATA").write_text(
                    f"Metadata-Version: 2.4\nName: {name}\nVersion: 1.0\n{headers}\n",
                    encoding="utf-8")
                if not keep_licence:
                    (di / "LICENSE").unlink()
        return out

    monkeypatch.setattr(bp, "_run", run)


def test_build_records_the_classification_in_the_report_and_pack_json(bp, tmp_path,
                                                                       monkeypatch):
    from yazses.packs.install import extract_archive

    dist = _fake_bundle(tmp_path)
    _install_fake(monkeypatch, bp, tmp_path)
    assert bp.main(_argv(tmp_path, dist)) == 0
    report = json.loads((tmp_path / "work" / "build-report.json").read_bytes())
    assert sorted(report["packs"]) == ["diarization", "parakeet"]
    for name, entry in report["packs"].items():
        gate = entry["licence_gate"]
        assert gate["ok"] and gate["problems"] == []
        assert entry["pack_json"]["licences"] == [
            {"name": d["name"], "version": "1.0", "licence": "MIT", "class": "permissive"}
            for d in entry["pack_json"]["distributions"]]
        # The runtime's own extractor accepts the pack with the new pack.json key.
        manifest = extract_archive(Path(entry["archive"]), tmp_path / "x" / name)
        assert manifest.name == name


def test_build_withholds_a_pack_the_licence_gate_fails(bp, tmp_path, monkeypatch):
    dist = _fake_bundle(tmp_path)
    _install_fake(monkeypatch, bp, tmp_path)
    _rewrite_metadata(monkeypatch, bp, {
        "sherpa-onnx": ("License-Expression: GPL-3.0-or-later", True),
    })
    assert bp.main(_argv(tmp_path, dist)) == 0
    report = json.loads((tmp_path / "work" / "build-report.json").read_bytes())
    assert sorted(report["packs"]) == ["parakeet"]
    why = report["withheld"]["diarization"]
    assert why.startswith("licence gate: ") and "recorded owner approval" in why
    doc = json.loads((dist / bp.EMBEDDED_INDEX).read_bytes())
    assert [p["name"] for p in doc["packs"]] == ["parakeet"]
    assert not list((tmp_path / "out").glob("*diarization*"))


def test_build_withholds_a_pack_with_a_missing_licence_file(bp, tmp_path, monkeypatch):
    dist = _fake_bundle(tmp_path)
    _install_fake(monkeypatch, bp, tmp_path)
    _rewrite_metadata(monkeypatch, bp, {"onnx-asr": ("License-Expression: MIT", False)})
    assert bp.main(_argv(tmp_path, dist)) == 0
    report = json.loads((tmp_path / "work" / "build-report.json").read_bytes())
    assert "no licence file" in report["withheld"]["parakeet"]
    assert sorted(report["packs"]) == ["diarization"]


def test_build_ships_lgpl_with_source_md_the_runtime_accepts(bp, tmp_path, monkeypatch):
    from yazses.packs.install import extract_archive

    dist = _fake_bundle(tmp_path)
    _install_fake(monkeypatch, bp, tmp_path)
    _rewrite_metadata(monkeypatch, bp, {
        "sherpa-onnx": ("License-Expression: LGPL-2.1-only\n"
                        "Project-URL: Repository, https://github.com/example/sherpa", True),
    })
    assert bp.main(_argv(tmp_path, dist)) == 0
    report = json.loads((tmp_path / "work" / "build-report.json").read_bytes())
    entry = report["packs"]["diarization"]
    assert entry["licence_gate"]["source_offer"] == "LICENSES/SOURCE.md"
    with zipfile.ZipFile(entry["archive"]) as zf:
        md = zf.read("LICENSES/SOURCE.md").decode("utf-8")
        record = {f["path"] for f in json.loads(zf.read("RECORD.json"))["files"]}
    assert "https://github.com/example/sherpa" in md and "LGPL-2.1-only" in md
    assert "LICENSES/SOURCE.md" in record
    extract_archive(Path(entry["archive"]), tmp_path / "x")
    assert (tmp_path / "x" / "LICENSES" / "SOURCE.md").is_file()


def test_spike_mode_records_the_gate_but_does_not_withhold(bp, tmp_path, monkeypatch):
    """--skip-probe is the Phase 0 diagnostic: like a DLL conflict, a licence failure is
    reported there, not used to drop the pack the spike is trying to measure."""
    dist = _fake_bundle(tmp_path)
    _install_fake(monkeypatch, bp, tmp_path)
    _rewrite_metadata(monkeypatch, bp, {"sherpa-onnx": ("License: see file", True)})
    argv = [a for a in _argv(tmp_path, dist) if a != str(dist / "yazses-cli.exe")]
    argv[argv.index("--probe-exe")] = "--skip-probe"
    assert bp.main(argv) == 0
    report = json.loads((tmp_path / "work" / "build-report.json").read_bytes())
    gate = report["packs"]["diarization"]["licence_gate"]
    assert gate["ok"] is False and "not classifiable" in gate["problems"][0]
