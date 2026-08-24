"""A re-run must not destroy the measurement it replaces.

`write_result` writes every benchmark to a fixed filename, because the published tables
and their guards are keyed to those names. That is also how the first `test-other` matrix
was lost: the second run of the same command overwrote it, and the numbers this page had
been quoting survived only in a console log on a VM that will be deleted. The two runs
disagreed by 2.83 points on `large-v3`, so the displaced file was not redundant -- it was
half the finding.

These tests pin the three behaviours that make a re-run safe without changing what any
existing guard reads: the current name still holds the newest run, a *changed* file is
copied aside first, and an *unchanged* one is not (a reproducible benchmark re-run is the
normal case and must not accumulate identical copies).
"""
from __future__ import annotations

import json

import pytest

from tests.benchmark_deps import load

mod = load("_common", "_common.py")


@pytest.fixture()
def results(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
    return tmp_path


def _payload(wer: float, stamp: str) -> dict:
    return {"provenance": {"timestamp": stamp, "cpu_model": "x"}, "rows": [{"wer": wer}]}


def test_the_first_write_creates_no_history(results) -> None:
    mod.write_result("wer-test-other", _payload(4.86, "2026-08-23T10:00:00Z"))
    assert (results / "wer-test-other.json").exists()
    assert not (results / "history").exists(), "nothing was displaced; nothing to archive"


def test_a_changed_rerun_keeps_the_displaced_run(results) -> None:
    mod.write_result("wer-test-other", _payload(4.86, "2026-08-23T10:00:00Z"))
    mod.write_result("wer-test-other", _payload(7.69, "2026-08-23T23:55:32Z"))

    current = json.loads((results / "wer-test-other.json").read_text(encoding="utf-8"))
    assert current["rows"][0]["wer"] == 7.69, "the published name holds the newest run"

    archived = list((results / "history").glob("*.json"))
    assert len(archived) == 1, f"expected exactly one displaced run, got {archived}"
    assert json.loads(archived[0].read_text(encoding="utf-8"))["rows"][0]["wer"] == 4.86


def test_the_history_file_is_named_for_when_it_was_measured(results) -> None:
    """Not for when it was moved aside -- the clock at archive time says nothing."""
    mod.write_result("wer-test-other", _payload(4.86, "2026-08-23T10:00:00Z"))
    mod.write_result("wer-test-other", _payload(7.69, "2026-08-23T23:55:32Z"))
    name = next((results / "history").glob("*.json")).name
    assert name == "wer-test-other-2026-08-23T10-00-00Z.json"


def test_an_identical_rerun_archives_nothing(results) -> None:
    """The normal case. Six of eight engines reproduce bit-identically; if that filled
    the history directory, the directory would stop being a record of disagreement."""
    same = _payload(4.86, "2026-08-23T10:00:00Z")
    mod.write_result("wer-test-other", same)
    mod.write_result("wer-test-other", same)
    assert not (results / "history").exists()


def test_a_rerun_that_differs_only_in_provenance_is_still_kept(results) -> None:
    """Same numbers, different machine or different day, is a distinct measurement."""
    mod.write_result("wer", _payload(4.86, "2026-08-23T10:00:00Z"))
    mod.write_result("wer", _payload(4.86, "2026-08-24T10:00:00Z"))
    assert len(list((results / "history").glob("*.json"))) == 1


def test_three_runs_leave_two_in_history(results) -> None:
    for i, stamp in enumerate(("10:00:00", "11:00:00", "12:00:00")):
        mod.write_result("wer", _payload(4.0 + i, f"2026-08-23T{stamp}Z"))
    wers = sorted(
        json.loads(p.read_text(encoding="utf-8"))["rows"][0]["wer"]
        for p in (results / "history").glob("*.json")
    )
    assert wers == [4.0, 5.0]
    assert json.loads((results / "wer.json").read_text(encoding="utf-8"))["rows"][0]["wer"] == 6.0


def test_a_nested_name_cannot_write_outside_history(results) -> None:
    """`write_result("probes/x", ...)` is a supported name. Flattened, not nested, so the
    history directory stays one level deep and is enumerable by a single glob."""
    (results / "probes").mkdir()
    mod.write_result("probes/largev3-instability", _payload(1.0, "2026-08-23T10:00:00Z"))
    mod.write_result("probes/largev3-instability", _payload(2.0, "2026-08-23T11:00:00Z"))
    archived = list((results / "history").glob("*.json"))
    assert len(archived) == 1
    assert archived[0].name.startswith("probes-largev3-instability-")


def test_a_result_with_no_provenance_is_still_archived(results) -> None:
    """Two files in `results/` once had no provenance block. An un-stamped file is
    exactly the one whose loss would be hardest to notice, so it must not be the one
    the archive step skips."""
    (results / "vad.json").write_text('{"rows": [{"wer": 1.0}]}', encoding="utf-8")
    mod.write_result("vad", {"rows": [{"wer": 2.0}]})
    archived = list((results / "history").glob("*.json"))
    assert len(archived) == 1
    assert "unstamped" in archived[0].name


def test_unparseable_previous_content_does_not_lose_the_file(results) -> None:
    """A truncated write from a killed run is still evidence that a run happened."""
    (results / "wer.json").write_text("{not json", encoding="utf-8")
    mod.write_result("wer", _payload(1.0, "2026-08-23T10:00:00Z"))
    archived = list((results / "history").glob("*.json"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == "{not json"


def test_the_archive_never_raises_into_a_benchmark(results, monkeypatch) -> None:
    """A two-hour decode must not die because the archive step could not write."""
    mod.write_result("wer", _payload(1.0, "2026-08-23T10:00:00Z"))

    real_mkdir = mod.Path.mkdir

    def boom(self, *a, **kw):
        if self.name == "history":
            raise PermissionError("read-only")
        return real_mkdir(self, *a, **kw)

    monkeypatch.setattr(mod.Path, "mkdir", boom)
    path = mod.write_result("wer", _payload(2.0, "2026-08-23T11:00:00Z"))
    assert json.loads(path.read_text(encoding="utf-8"))["rows"][0]["wer"] == 2.0
