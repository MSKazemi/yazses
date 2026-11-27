"""Speech profiles and the hardware pick (#930): fake machines, no probe, no network."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import SttConfig
from yazses.language.capability import find_capability
from yazses.stt import profiles as sp

runner = CliRunner()

ROOT = Path(__file__).resolve().parent.parent
BIG = sp.Machine(ram_gb=33.3, logical_cpus=20)


# ---- the table is the benchmarks page ---------------------------------------------------

def _section(text: str, start: str, end: str) -> str:
    assert start in text and end in text, f"benchmarks.md lost {start!r} or {end!r}"
    return text.split(start, 1)[1].split(end, 1)[0]


def _row(section: str, model: str) -> list[str]:
    for line in section.splitlines():
        cells = [c.strip().replace("*", "") for c in line.strip().strip("|").split("|")]
        if cells[0].split()[:1] == [f"`{model}`"]:
            return cells
    raise AssertionError(f"no row for {model}")


@pytest.mark.parametrize("profile", sp.PROFILES, ids=lambda p: p.id)
def test_every_figure_is_the_one_on_the_benchmarks_page(profile) -> None:
    page = (ROOT / "docs" / "benchmarks.md").read_text(encoding="utf-8")
    accuracy = _row(
        _section(page, "## Accuracy — word error rate", "## Every engine"),
        profile.english_model,
    )
    assert accuracy[1] == f"{profile.wer_pct:.2f} %"
    assert accuracy[-1] == f"{profile.disk_mb} MB"
    memory = _row(
        _section(page, "**Re-measured 2026-10-21.**", "## Voice-activity gate"),
        profile.english_model,
    )
    # "342–344 MB" is a range over two runs; the table carries the upper end.
    assert int(re.findall(r"\d+", memory[-1])[-1]) == profile.peak_rss_mb


def test_the_profiles_name_real_checkpoints_in_both_languages() -> None:
    assert [p.id for p in sp.PROFILES] == ["fast", "balanced", "accurate"]
    for profile in sp.PROFILES:
        english = find_capability("faster-whisper", profile.english_model)
        multi = find_capability("faster-whisper", profile.multilingual_model)
        assert english is not None and not english.multilingual
        assert multi is not None and multi.multilingual


def test_balanced_is_the_shipped_default() -> None:
    assert sp.get_profile("balanced").english_model == SttConfig().model


def test_an_unknown_profile_name_is_an_error() -> None:
    with pytest.raises(KeyError):
        sp.get_profile("parakeet")


# ---- recommend() on fake hardware -------------------------------------------------------

@pytest.mark.parametrize(
    ("ram", "expected"),
    [
        (1.0, "tiny.en"),
        (2.1, "tiny.en"),
        (2.9, "tiny.en"),
        (sp.RAM_FAST_BELOW_GB, "base.en"),
        (3.8, "base.en"),
        (8.3, "base.en"),
        (128.0, "base.en"),
        (None, "base.en"),
    ],
)
def test_ram_decides_the_english_pick(ram, expected) -> None:
    assert sp.recommend(sp.Machine(ram_gb=ram, logical_cpus=8)).model == expected


@pytest.mark.parametrize("cpus", [None, 1, 2, 4, 64])
def test_the_cpu_count_never_changes_the_pick(cpus) -> None:
    result = sp.recommend(sp.Machine(ram_gb=16.0, logical_cpus=cpus))
    assert result.profile is not None and result.profile.id == "balanced"


def test_accurate_is_never_picked_for_english() -> None:
    result = sp.recommend(sp.Machine(ram_gb=512.0, logical_cpus=256))
    assert result.model == "base.en"
    assert any("'accurate' is not suggested" in n for n in result.notes)


def test_fewer_cpus_than_any_measured_machine_is_said() -> None:
    few = sp.recommend(sp.Machine(ram_gb=8.0, logical_cpus=2))
    enough = sp.recommend(sp.Machine(ram_gb=8.0, logical_cpus=sp.MIN_TIMED_CPUS))
    assert any("this machine has 2" in n for n in few.notes)
    assert not any("this machine has" in n for n in enough.notes)


def test_unread_ram_is_said_rather_than_guessed() -> None:
    result = sp.recommend(sp.Machine())
    assert "could not be read" in result.reasons[0]


@pytest.mark.parametrize("language", ["de", "fa", "", "auto", "translate"])
def test_another_language_or_auto_detect_gets_a_multilingual_model(language) -> None:
    result = sp.recommend(BIG, language=language)
    assert result.model == "base"
    assert any("English-only checkpoints" in n for n in result.notes)


@pytest.mark.parametrize("language", ["en", "en-US", "EN"])
def test_english_spellings_get_the_english_model(language) -> None:
    assert sp.recommend(BIG, language=language).model == "base.en"


def test_a_language_profile_baseline_is_honoured() -> None:
    """`yazses language` already recommends `small` for Mandarin; do not contradict it."""
    result = sp.recommend(BIG, language="zh")
    assert result.profile is not None
    assert (result.profile.id, result.model) == ("accurate", "small")


def test_low_ram_beats_the_language_baseline_and_says_so() -> None:
    result = sp.recommend(sp.Machine(ram_gb=2.0, logical_cpus=4), language="zh")
    assert result.model == "tiny"
    assert any("'small'" in n and "more memory" in n for n in result.notes)


def test_a_language_no_profile_covers_gets_no_suggestion() -> None:
    result = sp.recommend(BIG, language="xx")
    assert result.profile is None and result.model is None
    assert result.reasons and result.reasons[0]


@pytest.mark.parametrize("engine", ["parakeet", "moonshine"])
def test_another_engine_gets_no_suggestion(engine) -> None:
    result = sp.recommend(BIG, engine=engine)
    assert result.model is None
    assert engine in result.reasons[0]


@pytest.mark.parametrize("engine", ["", None, "nonsense"])
def test_an_unknown_engine_is_what_the_factory_runs(engine) -> None:
    assert sp.recommend(BIG, engine=engine).model == "base.en"


# ---- the CLI ----------------------------------------------------------------------------

@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A fake host, config file and model cache; any download attempt fails the test."""
    config = tmp_path / "config.toml"
    state = SimpleNamespace(ram=2.0, config=config, cached={"base.en"})
    monkeypatch.setattr(
        cli, "get_platform",
        lambda: SimpleNamespace(paths=SimpleNamespace(config_file=config)),
    )
    monkeypatch.setattr(
        "yazses.platform.describe_host", lambda: SimpleNamespace(ram_gb=state.ram)
    )
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    monkeypatch.setattr("yazses.stt.download.is_cached", lambda name: name in state.cached)

    def no_download(*_a, **_k):
        raise AssertionError("`model recommend` must not download")

    monkeypatch.setattr("yazses.stt.download.download_stt_model", no_download)
    return state


def test_recommend_command_suggests_without_writing(machine) -> None:
    machine.config.write_text('[stt]\nmodel = "base.en"\n', encoding="utf-8")
    before = machine.config.read_bytes()
    result = runner.invoke(cli.app, ["model", "recommend"])
    assert result.exit_code == 0, result.output
    assert "Suggested:     fast (tiny.en)" in result.output
    assert "yazses model download tiny.en" in result.output
    assert "Nothing was changed or downloaded" in result.output
    assert machine.config.read_bytes() == before


def test_recommend_command_does_not_create_a_config(machine) -> None:
    machine.ram = 16.0
    result = runner.invoke(cli.app, ["model", "recommend"])
    assert result.exit_code == 0, result.output
    assert "Your config already uses it" in result.output
    assert "WER 4.07 %" in result.output
    assert not machine.config.exists()


def test_recommend_command_shows_no_english_figures_for_another_language(machine) -> None:
    machine.config.write_text('[stt]\nmodel = "small"\nlanguage = "de"\n', encoding="utf-8")
    result = runner.invoke(cli.app, ["model", "recommend"])
    assert result.exit_code == 0, result.output
    assert "WER" not in result.output
    assert "(tiny)" in result.output


def test_recommend_command_leaves_another_engine_alone(machine) -> None:
    machine.config.write_text('[stt]\nengine = "parakeet"\n', encoding="utf-8")
    result = runner.invoke(cli.app, ["model", "recommend"])
    assert result.exit_code == 0, result.output
    assert "nothing is suggested" in result.output
    assert "Profiles (" not in result.output
