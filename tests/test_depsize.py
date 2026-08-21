"""Telling the user what a feature costs, before they pay it (ADR-018).

`yazses features enable voiceprint` resolves `speechbrain` to torch plus the NVIDIA
CUDA stack — on a CPU-only, offline dictation tool. Nothing said so before the
download began.

What is tested here is the reasoning, not the numbers: the table is generated and
will change, so pinning its values would make this a change-detector. What must not
change is *which way the estimate errs*, that "already installed" is reported as
free rather than as unknown, and that a missing or broken table can never take the
catalogue down with it.
"""

from __future__ import annotations

import json

import pytest

from yazses.system import depsize


@pytest.fixture
def table(monkeypatch, tmp_path):
    """Install a known table, bypassing the lru_cache on the real one."""
    def _install(features: dict) -> None:
        path = tmp_path / "feature_sizes.json"
        path.write_text(json.dumps({"features": features}), encoding="utf-8")
        depsize._table.cache_clear()
        monkeypatch.setattr(depsize, "_TABLE_PATH", path)
    yield _install
    depsize._table.cache_clear()


HEAVY = {"voiceprint": {"download_mb": 2400.0, "packages": 40}}


# ---- the marginal figure ---------------------------------------------------


def test_nothing_missing_is_free_not_unknown(table):
    """A real case (`stt-moonshine` on a dev box) and worth saying plainly."""
    table(HEAVY)
    assert depsize.marginal_download_mb("voiceprint", []) == 0.0
    assert depsize.format_mb(0.0) == "already installed"


def test_everything_missing_costs_the_whole_closure(table):
    table(HEAVY)
    assert depsize.marginal_download_mb("voiceprint", ["speechbrain"]) == 2400.0


def test_an_unknown_feature_reports_unknown_rather_than_zero(table):
    """Zero would read as 'free'. Unknown must stay unknown."""
    table(HEAVY)
    assert depsize.marginal_download_mb("nosuchfeature", ["x"]) is None
    assert depsize.full_download_mb("nosuchfeature") is None
    assert depsize.format_mb(None) == ""
    assert depsize.download_note("nosuchfeature", ["x"]) == ""


def test_a_partial_install_over_estimates_rather_than_under(table):
    """The direction of the error is the whole design decision.

    Told "up to 2.4 GB" and downloading 300 MB, a user is mildly surprised. Told
    300 MB and handed 2.4 GB, they have been misled about the only thing they asked.
    """
    table({"tts": {"download_mb": 300.0, "packages": 3}})
    note = depsize.download_note("tts", ["kokoro_onnx"])
    assert "up to" in note, f"a partial install must be marked as an upper bound: {note}"
    assert depsize.marginal_download_mb("tts", ["kokoro_onnx"]) == 300.0


def test_a_full_install_is_not_hedged_as_an_upper_bound(table):
    table({"tts": {"download_mb": 300.0, "packages": 3}})
    note = depsize.download_note("tts", ["a", "b", "c"])
    assert "up to" not in note, f"nothing is installed, so this is the real figure: {note}"


# ---- rendering -------------------------------------------------------------


@pytest.mark.parametrize(
    "mb, expected",
    [(2400.0, "~2.4 GB"), (1000.0, "~1.0 GB"), (300.0, "~300 MB"),
     (12.4, "~12 MB"), (3.5, "~3.5 MB"), (0.0, "already installed"), (None, "")],
)
def test_sizes_render_at_a_sensible_precision(mb, expected):
    assert depsize.format_mb(mb) == expected


def test_a_single_package_is_not_pluralised(table):
    """`(1 packages)` is the kind of thing that makes a tool look unfinished."""
    table({"prosody": {"download_mb": 10.8, "packages": 1}})
    assert "(1 package)" in depsize.download_note("prosody", ["parselmouth"])


def test_several_packages_are_pluralised(table):
    table({"gaze": {"download_mb": 219.4, "packages": 12}})
    assert "(12 packages)" in depsize.download_note("gaze", ["cv2", "mediapipe"])


def test_a_large_download_is_flagged(table):
    table(HEAVY)
    assert depsize.is_a_large_download("voiceprint", ["speechbrain"]) is True


def test_a_small_download_is_not_flagged(table):
    table({"chinese-script": {"download_mb": 1.2, "packages": 1}})
    assert depsize.is_a_large_download("chinese-script", ["opencc"]) is False


def test_an_unknown_size_is_not_flagged_as_large(table):
    """Unknown must not be treated as alarming any more than as free."""
    table({})
    assert depsize.is_a_large_download("whatever", ["x"]) is False


# ---- the catalogue column --------------------------------------------------


def test_the_catalogue_quotes_the_whole_closure_not_this_machine(table):
    """The listing is a reference table, not a per-machine quote.

    `features enable` answers "what will *I* pay now" and uses the marginal
    figure. The catalogue answers "what does this cost", for a reader who may not
    have any of it — so a dev box that happens to have torch must not advertise
    a 3 GB feature to everyone else as free.
    """
    table(HEAVY)
    assert depsize.catalogue_size_label("voiceprint", True) == "~2.4 GB"


def test_a_feature_with_no_dependencies_shows_nothing(table):
    """Pure-logic features download nothing; a `0 MB` column would be noise."""
    table(HEAVY)
    assert depsize.catalogue_size_label("reflow", False) == ""


def test_an_unpriced_feature_shows_nothing_rather_than_a_guess(table):
    table({})
    assert depsize.catalogue_size_label("voiceprint", True) == ""


def test_a_zero_sized_feature_is_not_labelled_already_installed(table):
    """`format_mb(0)` says "already installed" — true of a machine, not of a table."""
    table({"tiny": {"download_mb": 0.0, "packages": 0}})
    assert depsize.catalogue_size_label("tiny", True) == ""


def test_the_label_fits_the_column(table):
    """The CLI pads this to a fixed width; an overflow would shift ADVICE."""
    table({"big": {"download_mb": 3065.9, "packages": 37}})
    assert len(depsize.catalogue_size_label("big", True)) <= depsize.SIZE_COLUMN_WIDTH


# ---- it must never break the catalogue -------------------------------------


def test_a_missing_table_degrades_quietly(monkeypatch, tmp_path):
    depsize._table.cache_clear()
    monkeypatch.setattr(depsize, "_TABLE_PATH", tmp_path / "does-not-exist.json")
    assert depsize._table() == {}
    assert depsize.download_note("voiceprint", ["speechbrain"]) == ""
    depsize._table.cache_clear()


def test_a_corrupt_table_degrades_quietly(monkeypatch, tmp_path):
    """`yazses features` failing because a size file is malformed is a bad trade."""
    path = tmp_path / "feature_sizes.json"
    path.write_text("{not json", encoding="utf-8")
    depsize._table.cache_clear()
    monkeypatch.setattr(depsize, "_TABLE_PATH", path)
    assert depsize._table() == {}
    depsize._table.cache_clear()


# ---- the table and the registry must not drift apart -----------------------


def test_the_size_table_ships_inside_the_package():
    """A data file outside the package directory never reaches a user.

    `pyproject.toml` builds the wheel from `packages = ["src/yazses"]`, so anything
    under that path ships and anything beside it does not. Verified against a real
    `uv build` when this landed; this is the cheap standing check.

    The failure this prevents is silent in the worst way: the table would be absent
    at runtime, `_table()` would return `{}` exactly as designed for a corrupt file,
    and every Cost line would simply not appear. Users would see the pre-ADR-018
    behaviour and nothing would report an error. This project has shipped that shape
    before — the Windows icon hidden behind an `else None`, and the provenance glob
    that silently matched nothing.
    """
    from pathlib import Path

    import yazses

    package_root = Path(yazses.__file__).resolve().parent
    assert depsize._TABLE_PATH.resolve().is_relative_to(package_root), (
        f"{depsize._TABLE_PATH} is outside {package_root}, so it will not be "
        f"included in the wheel and every download size will silently vanish"
    )
    assert depsize._TABLE_PATH.suffix == ".json"


def test_every_feature_with_dependencies_is_priced():
    """A feature that gains a dependency must go stale loudly, not silently.

    This reads the *real* committed table on purpose — it is the drift guard, and a
    fixture would defeat it. Regenerate with `scripts/gen-feature-sizes.py`.
    """
    from yazses.system.features import _FEATURE_DEPS

    depsize._table.cache_clear()
    priced = set(depsize._table())
    if not priced:
        pytest.skip("no size table committed yet")
    unpriced = sorted(set(_FEATURE_DEPS) - priced)
    assert not unpriced, (
        f"these features install packages but have no size: {unpriced}. Run "
        f"`uv run python scripts/gen-feature-sizes.py` and commit the result."
    )
