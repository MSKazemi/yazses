"""The provenance check must not be satisfiable by finding nothing to check.

`scripts/verify-provenance.py` answers a question nothing in this repository asked
before 2026-08-24: does a *published* artifact actually have an attestation GitHub
will serve? Four workflows call `actions/attest-build-provenance`, and
`test_release_provenance_assets.py` proves the workflow attaches a bundle -- but
`gh attestation verify` appeared exactly once in the repo, inside a comment.

The danger in a checker like this is not a wrong answer, it is a vacuous one. If the
set of attestable suffixes comes back empty, every release passes: nothing was
required, so nothing was missing. These tests exist mostly to make that impossible.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "verify_provenance", ROOT / "scripts" / "verify-provenance.py"
    )
    m = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(m)
    return m


# --- the derivation, which must never come back empty --------------------------------


def test_the_attested_suffixes_are_derived_from_the_real_workflows(mod):
    found = mod.attested_suffixes()
    assert found, "no workflow appears to attest anything — the parse is broken"
    # The three artifact kinds this project actually ships and attests.
    assert {".exe", ".dmg", ".deb"} <= found, found


def test_a_workflow_tree_that_attests_nothing_yields_nothing(tmp_path, mod):
    """The empty case must be *reachable*, so the caller's guard is not dead code."""
    (tmp_path / "plain.yml").write_text("on: push\njobs: {}\n", encoding="utf-8")
    assert mod.attested_suffixes(tmp_path) == set()


def test_an_empty_derivation_fails_the_command_rather_than_passing_it(tmp_path, mod, capsys):
    """A check with nothing to check must not report success."""
    sums = tmp_path / "SHA256SUMS.txt"
    sums.write_text(f"{'a' * 64}  YazSes-9.9.9-windows-x64.exe\n", encoding="utf-8")
    empty = tmp_path / "workflows"
    empty.mkdir()
    original = mod.WORKFLOWS
    mod.WORKFLOWS = empty
    try:
        assert mod.main(["--sums", str(sums)]) == 1
    finally:
        mod.WORKFLOWS = original
    assert "no workflow appears to attest anything" in capsys.readouterr().err


def test_a_new_attested_suffix_is_picked_up_without_editing_this_test(tmp_path, mod):
    """Add a channel that attests a .pkg and it is covered the same day."""
    (tmp_path / "pkg.yml").write_text(
        "jobs:\n  b:\n    steps:\n"
        "      - uses: actions/attest-build-provenance@v2\n"
        "        with:\n"
        "          subject-path: dist/YazSes-*.pkg\n",
        encoding="utf-8",
    )
    assert mod.attested_suffixes(tmp_path) == {".pkg"}


# --- reading the published checksums --------------------------------------------------


REAL_SUMS = """\
452685cd12921f00de4cefe91f24919f6be7c730c62d24db5ffe19f35d5591ee  YazSes-2.30.0-windows-arm64.exe
1b40703e5e91838f6e7627357ebf780cdc2d98b9940887debcf230f76508746a  YazSes-2.30.0-windows-x64.exe
7e04f88cbb206f42fe3604d25eae957071dcf558f3690cc500ebd22860fdb7f6  YazSes-2.30.0-windows-arm64.intoto.jsonl
d7b8c788316ff83dc9280cd056ab42f044562027d3a6a9b4f2ce820586a4c373  YazSes-2.30.0-windows-x64.intoto.jsonl
"""


def test_it_parses_the_file_the_release_actually_publishes(mod):
    """Verbatim from the v2.30.0 release, not a shape invented here."""
    sums = mod.parse_sums(REAL_SUMS)
    assert len(sums) == 4
    assert sums["YazSes-2.30.0-windows-x64.exe"].startswith("1b40703e")


def test_the_binary_star_marker_is_not_read_as_part_of_the_name(mod):
    """`sha256sum -b` writes ` *name`; the star is a mode flag, not the filename."""
    sums = mod.parse_sums(f"{'b' * 64} *YazSes-1.0.0-windows-x64.exe\n")
    assert list(sums) == ["YazSes-1.0.0-windows-x64.exe"]


def test_only_attestable_artifacts_are_required_to_have_one(mod):
    """`SHA256SUMS.txt` and the `.intoto.jsonl` bundles are not themselves attested."""
    wanted = mod.needing_attestation(mod.parse_sums(REAL_SUMS), {".exe", ".dmg", ".deb"})
    assert set(wanted) == {
        "YazSes-2.30.0-windows-arm64.exe",
        "YazSes-2.30.0-windows-x64.exe",
    }


def test_a_release_with_no_attestable_asset_is_not_an_error(mod, tmp_path, capsys):
    """A docs-only or source-only tag has nothing to attest, which is not a failure."""
    sums = tmp_path / "S.txt"
    sums.write_text(f"{'c' * 64}  notes.txt\n", encoding="utf-8")
    assert mod.main(["--sums", str(sums)]) == 0
    assert "nothing to verify" in capsys.readouterr().out
