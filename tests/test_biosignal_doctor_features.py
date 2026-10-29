"""The doctor row and the feature-registry row for `[biosignal]` (ADR-v2-152).

``_biosignal_check`` says what stops an enabled switch from working without opening
anything: SKIP when off, WARN on an empty source, FAIL on a source that cannot work, WARN on a
missing / stale / wrong-board calibration. The registry row is the one switch a user reaches
through `yazses features`; it must carry its metadata, flip exactly one key, and never ask
for BrainFlow (that comes with the `emg-band` extra, installed by the user on purpose).

Profiles are saved under ``tmp_path``; no board, port or network is touched.
"""
from __future__ import annotations

import dataclasses
import inspect
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.biosignal.calibration import CalibrationProfile, default_profile_path, save_profile
from yazses.config import BiosignalConfig, Config, load_config
from yazses.system import doctor
from yazses.system.doctor import _biosignal_check
from yazses.system.features import (
    _CATEGORIES,
    _EXAMPLES,
    _FEATURE_DEPS,
    _UNWIRED,
    _USE_CASES,
    CAT_ACCESS,
    EXPERIMENTAL,
    _registry,
    default_enabled_slugs,
    enable_caveat,
    feature_packages,
    feature_status,
    find_feature,
    toggleable_slugs,
)

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
TITLE = "Biosignal switch"


def _cfg(**bio) -> Config:
    cfg = Config()
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), **bio)
    return cfg


def _profile(board_id: str = "brainflow:0", created: datetime | None = None) -> CalibrationProfile:
    return CalibrationProfile(
        created_at=(created or NOW - timedelta(days=1)).isoformat(),
        board_id=board_id,
        channels=("ch1",),
        channel_kinds=("emg",),
        fs=250.0,
        baseline_rms=1.0,
        noise_floor=0.1,
        thresholds={"light": 5.0, "hard": 9.0},
        phases=("baseline", "mvc"),
    )


def _save(tmp_path: Path, profile: CalibrationProfile) -> Path:
    path = default_profile_path(tmp_path)
    save_profile(profile, path)
    return path


def _check(cfg, tmp_path, **kw):
    kw.setdefault("brainflow_present", True)
    kw.setdefault("now", NOW)
    return _biosignal_check(cfg, tmp_path, **kw)


def _lines(row) -> list[str]:
    return [line for line in row[2].splitlines() if line.strip()]


# ------------------------------------------------------------------------------ SKIP / empty


def test_off_is_a_skip_not_a_problem(tmp_path):
    title, status, detail = _check(_cfg(), tmp_path)
    assert (title, status) == (TITLE, "SKIP")
    assert "off" in detail and "yazses biosignal doctor" in detail


def test_off_stays_a_skip_whatever_else_is_set(tmp_path):
    row = _check(_cfg(enabled=False, source="bogus:1"), tmp_path)
    assert row[1] == "SKIP"


def test_a_config_without_the_section_is_a_skip(tmp_path):
    assert _check(SimpleNamespace(), tmp_path)[1] == "SKIP"


@pytest.mark.parametrize("source", ["", "   "])
def test_an_empty_source_is_a_warning_with_a_fix(tmp_path, source):
    row = _check(_cfg(enabled=True, source=source), tmp_path)
    assert row[1] == "WARN"
    assert "source is empty" in row[2]
    assert "fix:" in row[2] and "synthetic" in row[2]


# ------------------------------------------------------------------------------ OK


def test_synthetic_is_ok_and_needs_no_calibration(tmp_path):
    row = _check(_cfg(enabled=True, source="synthetic"), tmp_path)
    assert row[0:2] == (TITLE, "OK")
    assert "source synthetic" in row[2] and "Nothing was opened" in row[2]


def test_a_synthetic_variant_is_ok(tmp_path):
    assert _check(_cfg(enabled=True, source="synthetic:emg"), tmp_path)[1] == "OK"


def test_an_eeg_only_headset_needs_no_squeeze_calibration(tmp_path):
    """Muse has no muscle channel to calibrate: the blink switch needs none."""
    assert _check(_cfg(enabled=True, source="brainflow:38"), tmp_path)[1] == "OK"


def test_a_fresh_matching_profile_is_ok(tmp_path):
    _save(tmp_path, _profile("brainflow:0"))
    row = _check(_cfg(enabled=True, source="brainflow:0:/dev"), tmp_path)
    # the serial port /dev exists as a directory path, so only the calibration is in play
    assert row[1] == "OK", row[2]


# ------------------------------------------------------------------------------ FAIL


@pytest.mark.parametrize("source", ["bogus:1", "brainflow:x", "serial", "synthetic2"])
def test_a_source_that_does_not_parse_is_a_fail(tmp_path, source):
    row = _check(_cfg(enabled=True, source=source), tmp_path)
    assert row[1] == "FAIL"
    assert f"source {source!r} is not usable" in row[2]
    assert "fix:" in row[2]


def test_a_missing_recording_is_a_fail_naming_the_path(tmp_path):
    missing = tmp_path / "nope.csv"
    row = _check(_cfg(enabled=True, source=f"file:{missing}"), tmp_path)
    assert row[1] == "FAIL"
    assert "recording not found" in row[2] and str(missing) in row[2]


def test_an_existing_recording_is_not_a_fail(tmp_path):
    recording = tmp_path / "rec.csv"
    recording.write_text("1,2,3\n", encoding="utf-8")
    row = _check(_cfg(enabled=True, source=f"file:{recording}"), tmp_path)
    assert row[1] != "FAIL", row[2]


def test_a_recording_spec_with_no_path_is_a_fail(tmp_path):
    """`file:` cannot be opened by the daemon (`open_source` refuses it), so the doctor
    must say so rather than moving on to the calibration check."""
    row = _check(_cfg(enabled=True, source="file:"), tmp_path)
    assert row[1] == "FAIL", row


def test_a_failed_source_does_not_also_report_the_calibration(tmp_path):
    row = _check(_cfg(enabled=True, source="bogus:1"), tmp_path)
    assert "calibration" not in row[2]


def test_a_brainflow_source_without_brainflow_is_a_fail(tmp_path):
    row = _check(_cfg(enabled=True, source="brainflow:38"), tmp_path, brainflow_present=False)
    assert row[1] == "FAIL"
    assert "BrainFlow is not installed" in row[2]
    assert "fix:" in row[2] and "emg-band" in row[2]


def test_missing_brainflow_is_detected_from_the_real_import_machinery(tmp_path, monkeypatch):
    """No injected flag: an unimportable `brainflow` (None in sys.modules) is what is seen."""
    monkeypatch.setitem(sys.modules, "brainflow", None)
    row = _biosignal_check(_cfg(enabled=True, source="brainflow:38"), tmp_path, now=NOW)
    assert row[1] == "FAIL"
    assert "BrainFlow is not installed" in row[2]


def test_brainflow_present_does_not_fail_a_brainflow_source(tmp_path):
    assert _check(_cfg(enabled=True, source="brainflow:38"), tmp_path)[1] == "OK"


def test_brainflow_is_not_needed_for_a_synthetic_source(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "brainflow", None)
    assert _biosignal_check(_cfg(enabled=True, source="synthetic"), tmp_path, now=NOW)[1] == "OK"


def test_a_fail_outranks_a_warning(tmp_path):
    row = _check(_cfg(enabled=True, source="brainflow:0"), tmp_path, brainflow_present=False)
    assert row[1] == "FAIL"
    assert "serial port" in row[2]  # the WARN lines are still reported beside the FAIL


# ------------------------------------------------------------------------------ WARN: ports


def test_a_board_that_needs_a_serial_port_and_has_none_is_a_warning(tmp_path):
    _save(tmp_path, _profile("brainflow:0"))
    row = _check(_cfg(enabled=True, source="brainflow:0"), tmp_path)
    assert row[1] == "WARN"
    assert "needs a serial port" in row[2] and "brainflow:0:/dev/ttyUSB0" in row[2]


def test_a_serial_port_that_is_not_there_is_a_warning(tmp_path):
    _save(tmp_path, _profile("brainflow:0"))
    gone = tmp_path / "ttyUSB9"
    # The port parser splits on ":" so a POSIX path is needed; tmp_path is one on this host.
    if not str(gone).startswith("/"):
        pytest.skip("POSIX port paths only")
    row = _check(_cfg(enabled=True, source=f"brainflow:0:{gone}"), tmp_path)
    assert row[1] == "WARN"
    assert f"serial port {gone} is not there" in row[2]


def test_a_serial_port_that_exists_is_fine(tmp_path):
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")
    if not str(port).startswith("/"):
        pytest.skip("POSIX port paths only")
    _save(tmp_path, _profile("brainflow:0"))
    assert _check(_cfg(enabled=True, source=f"brainflow:0:{port}"), tmp_path)[1] == "OK"


# ------------------------------------------------------------------------------ WARN: calibration


def test_a_missing_profile_is_a_warning_naming_where_it_looked(tmp_path):
    row = _check(_cfg(enabled=True, source="brainflow:0:/dev"), tmp_path)
    assert row[1] == "WARN"
    assert "no calibration profile" in row[2]
    assert str(default_profile_path(tmp_path)) in row[2]
    assert "yazses biosignal calibrate" in row[2]


def test_a_missing_profile_is_a_warning_not_a_fail(tmp_path):
    """The blink switch needs none and the squeeze stays off: dormant, not broken."""
    assert _check(_cfg(enabled=True, source="brainflow:0:/dev"), tmp_path)[1] != "FAIL"


def test_no_profile_is_fine_when_the_squeeze_detector_is_off(tmp_path):
    row = _check(_cfg(enabled=True, source="brainflow:0:/dev", emg=False), tmp_path)
    assert row[1] == "OK", row[2]


def test_a_named_calibration_file_is_the_one_that_is_read(tmp_path):
    elsewhere = tmp_path / "mine.json"
    save_profile(_profile("brainflow:0"), elsewhere)
    row = _check(_cfg(enabled=True, source="brainflow:0:/dev", calibration_file=str(elsewhere)),
                 tmp_path)
    assert row[1] == "OK", row[2]


def test_a_named_calibration_file_that_is_missing_names_that_path(tmp_path):
    missing = tmp_path / "absent.json"
    row = _check(_cfg(enabled=True, source="brainflow:0:/dev", calibration_file=str(missing)),
                 tmp_path)
    assert row[1] == "WARN" and str(missing) in row[2]


def test_a_stale_profile_is_a_warning(tmp_path):
    _save(tmp_path, _profile("brainflow:0", created=NOW - timedelta(days=31)))
    row = _check(_cfg(enabled=True, source="brainflow:0:/dev"), tmp_path)
    assert row[1] == "WARN"
    assert "calibration is old" in row[2] and "drift" in row[2]
    assert "yazses biosignal calibrate" in row[2]


def test_a_profile_from_just_inside_the_limit_is_not_stale(tmp_path):
    _save(tmp_path, _profile("brainflow:0", created=NOW - timedelta(days=29)))
    assert _check(_cfg(enabled=True, source="brainflow:0:/dev"), tmp_path)[1] == "OK"


def test_a_profile_dated_in_the_future_is_treated_as_stale(tmp_path):
    _save(tmp_path, _profile("brainflow:0", created=NOW + timedelta(days=3)))
    assert _check(_cfg(enabled=True, source="brainflow:0:/dev"), tmp_path)[1] == "WARN"


def test_a_profile_for_another_board_is_a_warning_naming_both(tmp_path):
    _save(tmp_path, _profile("brainflow:1"))
    row = _check(_cfg(enabled=True, source="brainflow:0:/dev"), tmp_path)
    assert row[1] == "WARN"
    assert "'brainflow:1'" in row[2] and "'brainflow:0'" in row[2]
    assert "another board or placement" in row[2]


def test_the_board_id_ignores_the_serial_port_part_of_the_spec(tmp_path):
    _save(tmp_path, _profile("brainflow:0"))
    assert _check(_cfg(enabled=True, source="brainflow:0:/dev"), tmp_path)[1] == "OK"


def test_a_wrong_board_profile_is_not_also_reported_stale(tmp_path):
    _save(tmp_path, _profile("brainflow:1", created=NOW - timedelta(days=90)))
    row = _check(_cfg(enabled=True, source="brainflow:0:/dev"), tmp_path)
    assert "another board" in row[2] and "calibration is old" not in row[2]


def test_an_unreadable_profile_counts_as_missing(tmp_path):
    default_profile_path(tmp_path).write_text("{not json", encoding="utf-8")
    row = _check(_cfg(enabled=True, source="brainflow:0:/dev"), tmp_path)
    assert row[1] == "WARN" and "no calibration profile" in row[2]


def test_every_problem_line_names_its_fix(tmp_path):
    row = _check(_cfg(enabled=True, source="brainflow:0"), tmp_path)
    assert row[2].count("fix:") == 2  # the missing port and the missing calibration
    assert len(_lines(row)) == 4


# ------------------------------------------------------------------------------ run_doctor


def test_run_doctor_reports_the_row_and_survives_a_check_that_raises():
    """The row is wired into `run_doctor`, behind a guard so it cannot hide later checks."""
    source = inspect.getsource(doctor.run_doctor)
    assert "_biosignal_check(cfg, paths.data_dir)" in source
    guarded = source[source.index("_biosignal_check(cfg, paths.data_dir)") - 120:
                     source.index("_biosignal_check(cfg, paths.data_dir)") + 260]
    assert "try:" in guarded and "except Exception" in guarded and "could not be checked" in guarded


def test_the_check_only_constructs_the_source_it_never_starts_it(tmp_path, monkeypatch):
    started: list[str] = []
    from yazses.biosignal import sources

    real_open = sources.open_source

    def open_and_watch(spec, **kw):
        source = real_open(spec, **kw)
        for name in ("start", "read", "read_block"):
            if hasattr(source, name):
                setattr(source, name, lambda *a, _n=name, **k: started.append(_n))
        return source

    monkeypatch.setattr(sources, "open_source", open_and_watch)
    assert _check(_cfg(enabled=True, source="synthetic"), tmp_path)[1] == "OK"
    assert started == []


# ------------------------------------------------------------------------------ registry row


def _row():
    rows = [d for d in _registry() if d.slug == "biosignal"]
    assert len(rows) == 1, "the biosignal row is missing or duplicated"
    return rows[0]


def test_the_slug_is_registered_exactly_once_with_its_metadata():
    row = _row()
    assert row.name and row.note and row.why
    assert row.tier == EXPERIMENTAL
    assert row.note.startswith("[biosignal]")
    assert callable(row.status)


def test_the_row_carries_example_use_case_and_category():
    assert len(_EXAMPLES["biosignal"]) > 20
    assert len(_USE_CASES["biosignal"]) > 20
    assert _CATEGORIES["biosignal"] == CAT_ACCESS
    feature = find_feature(Config(), "biosignal")
    assert feature is not None
    assert feature.example == _EXAMPLES["biosignal"]
    assert feature.use_case == _USE_CASES["biosignal"]
    assert feature.category == CAT_ACCESS


def test_the_row_is_wired_and_lives_in_the_biosignal_package():
    assert "biosignal" not in _UNWIRED
    assert feature_packages("biosignal") == ("biosignal",)
    assert find_feature(Config(), "biosignal").wired is True


def test_the_status_follows_the_config_key():
    cfg = Config()
    assert _row().status(cfg) is False
    cfg.biosignal.enabled = True
    assert _row().status(cfg) is True
    assert [f.on for f in feature_status(cfg) if f.slug == "biosignal"] == [True]


def test_enable_and_disable_touch_exactly_the_one_key():
    row = _row()
    assert row.on_writes == (("biosignal", "enabled", "true", False),)
    assert row.off_writes == (("biosignal", "enabled", "false", False),)
    assert "biosignal" in toggleable_slugs()


def test_the_feature_has_no_dependency_entry_so_enable_never_installs_brainflow():
    assert "biosignal" not in _FEATURE_DEPS
    row = _row()
    assert row.check_modules == () and row.pip_packages == ()
    feature = find_feature(Config(), "biosignal")
    assert feature.check_modules == () and feature.pip_packages == ()
    assert not any("brainflow" in p.lower() for p in feature.pip_packages)


def test_it_is_never_part_of_the_recommended_default_set():
    assert "biosignal" not in default_enabled_slugs()


def test_the_card_does_not_promise_thought_decoding():
    text = (_row().why + _row().note).lower()
    assert "never decodes thoughts" in text
    assert "experimental" in text


# ------------------------------------------------------------------------------ enable caveat


def test_enabling_with_no_source_warns_that_nothing_will_happen():
    caveat = enable_caveat("biosignal", Config())
    assert caveat is not None
    assert "does nothing until [biosignal] source" in caveat
    assert "synthetic" in caveat and "yazses restart" in caveat


def test_enabling_with_a_source_set_has_no_caveat():
    assert enable_caveat("biosignal", _cfg(source="synthetic")) is None


def test_a_blank_source_still_gets_the_caveat():
    assert enable_caveat("biosignal", _cfg(source="   ")) is not None


# ------------------------------------------------------------------------------ the CLI path


def _platform(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.toml"
    platform = SimpleNamespace(
        paths=SimpleNamespace(config_file=cfg_file, data_dir=tmp_path,
                              ipc_socket=tmp_path / "ipc.sock"),
        lifecycle=SimpleNamespace(is_running=lambda: False),
        ipc_client_factory=lambda _path: None,
    )
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    return cfg_file


def _no_installs(monkeypatch) -> list[object]:
    """Fail loudly on any attempt to run an installer from the CLI under test."""
    attempts: list[object] = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise AssertionError(f"enabling biosignal tried to run a subprocess: {args}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "check_call", refuse)
    return attempts


def test_enable_is_refused_without_force_because_it_is_experimental(monkeypatch, tmp_path):
    cfg_file = _platform(monkeypatch, tmp_path)
    _no_installs(monkeypatch)
    result = CliRunner().invoke(cli.app, ["features", "enable", "biosignal"])
    assert result.exit_code == 1
    assert "experimental" in result.output
    assert not cfg_file.exists() or load_config(cfg_file).biosignal.enabled is False


def test_enable_with_force_writes_one_key_and_installs_nothing(monkeypatch, tmp_path):
    cfg_file = _platform(monkeypatch, tmp_path)
    attempts = _no_installs(monkeypatch)
    result = CliRunner().invoke(cli.app, ["features", "enable", "biosignal", "--force"])
    assert result.exit_code == 0, result.output
    assert attempts == []
    cfg = load_config(cfg_file)
    assert cfg.biosignal.enabled is True
    assert cfg.biosignal.source == ""  # the user chooses the board; enabling never guesses
    assert "does nothing until [biosignal] source" in result.output  # the honest caveat
    assert "Install" not in result.output


def test_disable_turns_it_off_again(monkeypatch, tmp_path):
    cfg_file = _platform(monkeypatch, tmp_path)
    _no_installs(monkeypatch)
    runner = CliRunner()
    assert runner.invoke(cli.app, ["features", "enable", "biosignal", "--force"]).exit_code == 0
    assert load_config(cfg_file).biosignal.enabled is True
    assert runner.invoke(cli.app, ["features", "disable", "biosignal"]).exit_code == 0
    assert load_config(cfg_file).biosignal.enabled is False


def test_the_dependency_helpers_find_nothing_to_install_for_it():
    feature = find_feature(Config(), "biosignal")
    assert cli._missing_feature_deps(feature) == []
    assert cli._feature_deps_blocked(feature) is None
    assert cli._install_feature_deps(feature, skip=False) is True
