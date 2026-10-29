"""Tests for ``yazses biosignal ...``: the ``run_*`` command bodies and the daemon adapter.

Command bodies are called directly (``typer.testing.CliRunner(app)`` skips ``cli.main()``)
and their output is captured with ``capsys``; ``CliRunner`` is used only for argument
parsing, ``--help`` and exit-code smoke tests of the ``biosignal_app`` group, with the
context (config + data directory) pointed at ``tmp_path``. Nothing here opens hardware,
the network, the real data directory or the real calibration profile.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import typer.main
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.biosignal import cli_impl
from yazses.biosignal.calibration import CalibrationProfile, default_profile_path, save_profile
from yazses.biosignal.cli_impl import (
    FAILED,
    LEDGER_FILENAME,
    OK,
    UNUSABLE,
    BiosignalActivationSource,
    Switches,
    format_event,
    ledger_path,
    load_ledger,
    load_truth,
    persist_session_ledger,
    profile_path,
    run_boards,
    run_doctor,
    run_evaluate,
    run_monitor,
    run_profile_clear,
    run_profile_show,
    run_record,
    run_replay,
    run_report,
    source_spec,
    switches_from,
)
from yazses.biosignal.evaluate import CAVEAT
from yazses.biosignal.fprate import PROXY_NOTE, ActivationLedger
from yazses.biosignal.types import BioEvent, EventKind
from yazses.config import Config

runner = CliRunner()
posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")

SUBCOMMANDS = [
    ["doctor"], ["calibrate"], ["monitor"], ["replay"], ["report"], ["record"], ["evaluate"],
    ["profile"], ["profile-clear"], ["boards"], ["field-test"],
]


# ---------------------------------------------------------------------------
# helpers and fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg() -> Config:
    """A default config: biosignal off, no source."""
    return Config()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def cli_ctx(monkeypatch, cfg, data_dir):
    """Point every ``biosignal`` Typer command at a private config and data directory."""
    monkeypatch.setattr(cli, "_biosignal_context", lambda: (cfg, data_dir))
    return cfg, data_dir


@pytest.fixture
def no_hardware(monkeypatch):
    """Doctor must not look at the machine's real BrainFlow install or serial ports."""
    monkeypatch.setattr(cli_impl, "_brainflow_state", lambda: (False, ""))
    monkeypatch.setattr(cli_impl, "_serial_ports", lambda: [])


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def make_profile(created_at: str | None = None) -> CalibrationProfile:
    """A profile with recognisable amplitudes, to prove they are never printed."""
    return CalibrationProfile(
        created_at=created_at or datetime.now(UTC).isoformat(),
        board_id="synthetic",
        channels=("Fp1", "EMG1"),
        channel_kinds=("eeg", "emg"),
        fs=500.0,
        baseline_rms=12.3456,
        noise_floor=7.6543,
        mvc_rms=2468.1357,
        light_rms=555.4321,
        thresholds={"onset": 98765.4321, "offset": 33333.3333},
        phases=("relax", "squeeze_hard"),
    )


AMPLITUDE_TEXT = ("12.3456", "7.6543", "2468.1357", "2468", "555.4321", "98765", "33333")


def write_ledger(data_dir: Path, *, activations=None, cancelled=None, active_s: int = 600,
                 sessions: int = 2) -> None:
    """Write the persisted counters the way the daemon does, via ``ActivationLedger.to_dict``."""
    now = [0.0]
    ledger = ActivationLedger(lambda: now[0])
    ledger.start()
    plan = activations if activations is not None else {EventKind.DOUBLE_BLINK: 8,
                                                        EventKind.JAW_CLENCH: 2}
    ids = []
    for kind, n in plan.items():
        for _ in range(n):
            ids.append((kind, ledger.record(BioEvent(kind, 0.0))))
    for kind, n in (cancelled if cancelled is not None else {EventKind.DOUBLE_BLINK: 2}).items():
        done = 0
        for k, event_id in ids:
            if k is kind and done < n:
                assert ledger.mark_cancelled(event_id)
                done += 1
    now[0] = float(active_s)
    ledger.stop()
    data = ledger.to_dict()
    data["sessions"] = sessions
    ledger_path(data_dir).write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture(scope="module")
def session_files(tmp_path_factory):
    """One seeded 33 s synthetic recording (CSV) with its truth file, shared by the module."""
    d = tmp_path_factory.mktemp("biosignal_session")
    csv, truth = d / "session.csv", d / "session.truth.json"
    code = run_record(Config(), d, source="synthetic", seconds=33.0, out=str(csv),
                      seed=0, truth_out=str(truth))
    assert code == OK
    return csv, truth


# ---------------------------------------------------------------------------
# the Typer group: --help, argument parsing, no `resume`
# ---------------------------------------------------------------------------


def test_biosignal_group_is_registered_on_the_real_app():
    """The group is reachable from the real entry point, with the documented commands."""
    group = typer.main.get_command(cli.app).commands["biosignal"]
    assert {"doctor", "calibrate", "monitor", "replay", "report", "record", "evaluate",
            "profile", "profile-clear", "boards"} <= set(group.commands)


def test_group_help_exits_zero_and_lists_commands():
    """``yazses biosignal --help`` works and names the subcommands."""
    result = runner.invoke(cli.app, ["biosignal", "--help"])
    assert result.exit_code == 0
    for name in ("doctor", "calibrate", "monitor", "replay", "report", "record", "evaluate",
                 "profile", "boards"):
        assert name in result.output


@pytest.mark.parametrize("path", SUBCOMMANDS, ids=lambda p: " ".join(p))
def test_every_subcommand_help_exits_zero(path):
    """``--help`` of every subcommand exits 0 and prints a usage line."""
    result = runner.invoke(cli.app, ["biosignal", *path, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage" in result.output


def test_there_is_no_resume_command():
    """``biosignal resume`` does not exist: a usage error, not a silent no-op."""
    result = runner.invoke(cli.app, ["biosignal", "resume"])
    assert result.exit_code == 2
    assert "No such command" in result.output


def test_bare_group_prints_help_instead_of_running_anything():
    """No subcommand: usage text (the exit code is Click's choice), nothing executed."""
    result = runner.invoke(cli.app, ["biosignal"])
    assert result.exit_code in (0, 2)
    assert "doctor" in result.output and "Usage" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["record"],                                              # --out is required
        ["record", "--out", "x.csv", "--seconds", "0"],          # min 1
        ["record", "--out", "x.csv", "--seed", "-1"],
        ["evaluate", "--seconds", "5"],                          # min 30
        ["evaluate", "--tolerance", "0"],                        # min 0.05
        ["monitor", "--seconds", "-1"],
        ["monitor", "--interval", "0.01"],                       # min 0.1
        ["replay"],                                              # file argument required
        ["profile-clear", "--bogus"],
    ],
    ids=lambda a: " ".join(a),
)
def test_bad_arguments_are_usage_errors(args, cli_ctx):
    """Out-of-range or missing arguments exit 2 before any command body runs."""
    result = runner.invoke(cli.app, ["biosignal", *args])
    assert result.exit_code == 2


def test_cli_boards_json_via_typer(cli_ctx):
    """The boards command is wired through Typer and prints parseable JSON."""
    result = runner.invoke(cli.app, ["biosignal", "boards", "--json"])
    assert result.exit_code == 0
    assert any(b["name"] == "synthetic" for b in json.loads(result.output)["boards"])


def test_cli_report_runs_against_the_private_data_dir(cli_ctx):
    """The Typer wrapper hands its own data dir to the command body."""
    _cfg, data_dir = cli_ctx
    write_ledger(data_dir)
    result = runner.invoke(cli.app, ["biosignal", "report", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["activations"] == 10


def test_cli_record_exit_codes(cli_ctx, tmp_path):
    """record through Typer: 0 on success, 2 when the target exists."""
    out = tmp_path / "t.csv"
    first = runner.invoke(cli.app, ["biosignal", "record", "--source", "synthetic",
                                    "--seconds", "3", "--out", str(out)])
    assert first.exit_code == 0, first.output
    assert out.stat().st_size > 0
    again = runner.invoke(cli.app, ["biosignal", "record", "--source", "synthetic",
                                    "--seconds", "3", "--out", str(out)])
    assert again.exit_code == 2
    forced = runner.invoke(cli.app, ["biosignal", "record", "--source", "synthetic",
                                     "--seconds", "3", "--out", str(out), "--force"])
    assert forced.exit_code == 0


def test_cli_doctor_with_synthetic_source_exits_zero(cli_ctx, no_hardware):
    """doctor needs no hardware and succeeds on a clean machine."""
    result = runner.invoke(cli.app, ["biosignal", "doctor", "--source", "synthetic"])
    assert result.exit_code == 0, result.output
    assert "scripted double blink detected" in result.output


def test_cli_profile_clear_confirmation(cli_ctx):
    """Typer: 'n' keeps the profile (0); no answer at all is a refusal (2); 'y' deletes."""
    cfg, data_dir = cli_ctx
    path = default_profile_path(data_dir)
    save_profile(make_profile(), path)
    declined = runner.invoke(cli.app, ["biosignal", "profile-clear"], input="n\n")
    assert declined.exit_code == 0 and path.exists()
    silent = runner.invoke(cli.app, ["biosignal", "profile-clear"])
    assert silent.exit_code == 2 and path.exists()
    confirmed = runner.invoke(cli.app, ["biosignal", "profile-clear"], input="y\n")
    assert confirmed.exit_code == 0 and not path.exists()


# ---------------------------------------------------------------------------
# small pure helpers
# ---------------------------------------------------------------------------


def test_switches_from_config_and_overrides(cfg):
    """Config flags are the default; an explicit choice (even False) replaces them."""
    assert switches_from(cfg.biosignal) == Switches(emg=True, double_blink=True, jaw_clench=False)
    assert switches_from(cfg.biosignal, emg=False, blink=False, clench=True) == Switches(
        emg=False, double_blink=False, jaw_clench=True)
    assert Switches(False, False, False).names() == "none"
    assert Switches(True, False, True).names() == "emg, jaw_clench"


def test_source_spec_prefers_the_command_line(cfg):
    """--source beats [biosignal] source; both are stripped."""
    cfg.biosignal.source = " file:a.csv "
    assert source_spec(cfg.biosignal) == "file:a.csv"
    assert source_spec(cfg.biosignal, " synthetic ") == "synthetic"
    cfg.biosignal.source = ""
    assert source_spec(cfg.biosignal) == ""


def test_profile_path_default_and_configured(cfg, data_dir, tmp_path):
    """Default profile lives in the data dir; [biosignal] calibration_file overrides it."""
    assert profile_path(cfg.biosignal, data_dir) == default_profile_path(data_dir)
    assert profile_path(cfg.biosignal, data_dir).parent == data_dir
    cfg.biosignal.calibration_file = str(tmp_path / "mine.json")
    assert profile_path(cfg.biosignal, data_dir) == tmp_path / "mine.json"


def test_format_event_is_one_aligned_row():
    """Time, kind, confidence and channel on one line; a squeeze level only when present."""
    plain = format_event(BioEvent(EventKind.DOUBLE_BLINK, 12.5, confidence=0.5, channel="Fp1"))
    assert "12.50s" in plain and "double_blink" in plain and "conf=0.50" in plain
    assert "ch=Fp1" in plain and "level" not in plain
    level = SimpleNamespace(value="hard")
    graded = format_event(BioEvent(EventKind.SQUEEZE_ON, 1.0, detail={"level": level}))
    assert "level=hard" in graded and "ch=" not in graded


# ---------------------------------------------------------------------------
# load_truth
# ---------------------------------------------------------------------------


def write_json(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_truth_accepts_a_list_and_the_events_wrapper(tmp_path):
    """Both file shapes load, normalise case, and come back sorted by time."""
    items = [{"kind": "Jaw_Clench", "t": 9}, {"kind": "double_blink", "t": 2.5}]
    for payload in (items, {"events": items}):
        events = load_truth(write_json(tmp_path / "t.json", payload))
        assert [(e.kind, e.t) for e in events] == [(EventKind.DOUBLE_BLINK, 2.5),
                                                   (EventKind.JAW_CLENCH, 9.0)]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"nope": 1}, "expected a list"),
        ([3], "not an object"),
        ([{"kind": "wink", "t": 1}], "unknown kind"),
        ([{"t": 1}], "unknown kind"),
        ([{"kind": "blink", "t": -1}], "non-negative"),
        ([{"kind": "blink", "t": True}], "non-negative"),
        ([{"kind": "blink", "t": "3"}], "non-negative"),
        ([{"kind": "blink"}], "non-negative"),
    ],
)
def test_load_truth_names_the_first_bad_entry(tmp_path, payload, message):
    """A malformed label is a ValueError that says what is wrong."""
    with pytest.raises(ValueError, match=message):
        load_truth(write_json(tmp_path / "t.json", payload))


def test_load_truth_rejects_oversized_and_non_json_files(tmp_path, monkeypatch):
    """Size cap and syntax errors both raise ValueError."""
    path = write_json(tmp_path / "t.json", [{"kind": "blink", "t": 1}])
    monkeypatch.setattr(cli_impl, "_MAX_TRUTH_BYTES", 5)
    with pytest.raises(ValueError, match="larger than"):
        load_truth(path)
    monkeypatch.undo()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_truth(bad)


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------


@posix_only
def test_record_csv_is_owner_only_and_replayable(cfg, data_dir, tmp_path, capsys):
    """A CSV recording is written, mode 0600, with the sensitivity warning on stderr."""
    out = tmp_path / "rec.csv"
    assert run_record(cfg, data_dir, source="synthetic", seconds=3.0, out=str(out)) == OK
    assert mode_of(out) == 0o600
    captured = capsys.readouterr()
    assert "raw biosignal data" in captured.err
    assert "mode 0600" in captured.out
    header = [ln for ln in out.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")][0]
    assert header.split(",") == ["Fp1:eeg", "Fp2:eeg", "EMG1:emg", "EMG2:emg"]


@posix_only
def test_record_npz_is_owner_only_and_has_the_documented_arrays(cfg, data_dir, tmp_path):
    """An .npz recording holds data/fs/channels and is mode 0600."""
    out = tmp_path / "rec.npz"
    assert run_record(cfg, data_dir, source="synthetic:emg", seconds=2.0, out=str(out)) == OK
    assert mode_of(out) == 0o600
    with np.load(out, allow_pickle=False) as npz:
        assert npz["data"].shape == (2, 2000)
        assert float(npz["fs"]) == 1000.0
        assert [str(c) for c in npz["channels"]] == ["EMG1:emg", "EMG2:emg"]


def test_record_refuses_to_overwrite_without_force(cfg, data_dir, tmp_path, capsys):
    """An existing --out is never replaced silently: exit 2, file untouched."""
    out = tmp_path / "rec.csv"
    out.write_text("precious", encoding="utf-8")
    assert run_record(cfg, data_dir, source="synthetic", seconds=2.0, out=str(out)) == UNUSABLE
    assert out.read_text(encoding="utf-8") == "precious"
    assert "already exists" in capsys.readouterr().err


@posix_only
def test_record_force_replaces_the_file_and_tightens_its_mode(cfg, data_dir, tmp_path):
    """--force overwrites, and the result is 0600 even if the old file was world-readable."""
    out = tmp_path / "rec.csv"
    out.write_text("old", encoding="utf-8")
    out.chmod(0o644)
    assert run_record(cfg, data_dir, source="synthetic", seconds=2.0, out=str(out),
                      force=True) == OK
    assert out.read_text(encoding="utf-8") != "old"
    assert mode_of(out) == 0o600


def test_record_refuses_when_only_the_truth_file_exists(cfg, data_dir, tmp_path):
    """--truth-out is protected like --out, and nothing is written before the refusal."""
    out, truth = tmp_path / "rec.csv", tmp_path / "truth.json"
    truth.write_text("keep", encoding="utf-8")
    code = run_record(cfg, data_dir, source="synthetic", seconds=2.0, out=str(out),
                      truth_out=str(truth))
    assert code == UNUSABLE
    assert not out.exists()
    assert truth.read_text(encoding="utf-8") == "keep"


@posix_only
def test_record_truth_out_writes_scripted_gestures_the_evaluator_can_read(session_files):
    """The truth file is owner-only JSON that load_truth accepts, with every kind scripted."""
    csv, truth = session_files
    assert mode_of(csv) == 0o600 and mode_of(truth) == 0o600
    events = load_truth(truth)
    kinds = {e.kind for e in events}
    assert {EventKind.DOUBLE_BLINK, EventKind.JAW_CLENCH, EventKind.SQUEEZE_ON,
            EventKind.SQUEEZE_OFF} <= kinds
    assert EventKind.BLINK not in kinds          # a blink pair is reported as one double blink
    assert all(0.0 <= e.t <= 33.0 for e in events)
    assert [e.t for e in events] == sorted(e.t for e in events)


def test_record_is_deterministic_for_a_seed(cfg, data_dir, tmp_path):
    """The same seed produces byte-identical truth files; another seed does not."""
    def truth_for(seed: int, name: str) -> str:
        t = tmp_path / f"{name}.json"
        run_record(cfg, data_dir, source="synthetic:eeg", seconds=40.0,
                   out=str(tmp_path / f"{name}.csv"), seed=seed, truth_out=str(t))
        return t.read_text(encoding="utf-8")

    assert truth_for(1, "a") == truth_for(1, "b")
    assert truth_for(1, "a2") != truth_for(2, "c")


def test_record_json_mode_prints_one_object(cfg, data_dir, tmp_path, capsys):
    """--json prints a parseable summary (and nothing else on stdout)."""
    out = tmp_path / "rec.csv"
    assert run_record(cfg, data_dir, source="synthetic", seconds=2.0, out=str(out),
                      as_json=True) == OK
    result = json.loads(capsys.readouterr().out)
    assert result["path"] == str(out)
    assert result["mode"] == "0600"
    assert result["channels"] == ["Fp1", "Fp2", "EMG1", "EMG2"]
    assert result["fs"] == 500.0
    assert result["bytes"] == out.stat().st_size
    assert result["truth"] is None


def test_record_short_synthetic_session_warns_about_missing_gestures(cfg, data_dir, tmp_path,
                                                                    capsys):
    """Under the warm-up length a synthetic recording holds no gestures, and says so."""
    assert run_record(cfg, data_dir, source="synthetic", seconds=3.0,
                      out=str(tmp_path / "r.csv")) == OK
    assert "no scripted gestures" in capsys.readouterr().err


def test_record_from_a_recording_ignores_truth_out(cfg, data_dir, tmp_path, session_files, capsys):
    """--truth-out only applies to a synthetic source; for a file it is ignored with a warning."""
    csv, _truth = session_files
    truth = tmp_path / "t.json"
    code = run_record(cfg, data_dir, source=f"file:{csv}", seconds=5.0,
                      out=str(tmp_path / "copy.csv"), truth_out=str(truth))
    assert code == OK
    assert not truth.exists()
    assert "only applies to a synthetic source" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"source": ""}, "No source"),
        ({"source": "synthetic", "out": ""}, "No output file"),
        ({"source": "synthetic", "out": "rec.txt"}, ".csv or .npz"),
        ({"source": "bogus"}, "Cannot open source"),
        ({"source": "file:/nonexistent/none.csv"}, "Cannot open source"),
        ({"source": "brainflow:abc"}, "Cannot open source"),
    ],
)
def test_record_unusable_requests_exit_2_and_write_nothing(cfg, data_dir, tmp_path, capsys,
                                                           kwargs, message):
    """Bad source, no output name or a wrong suffix: exit 2 with a reason."""
    kw = {"out": str(tmp_path / "rec.csv"), "seconds": 2.0, **kwargs}
    if kw["out"] == "rec.txt":
        kw["out"] = str(tmp_path / "rec.txt")
    assert run_record(cfg, data_dir, **kw) == UNUSABLE
    assert message in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == [data_dir] or not (tmp_path / "rec.csv").exists()


def test_record_uses_the_configured_source(cfg, data_dir, tmp_path):
    """With no --source, [biosignal] source is recorded."""
    cfg.biosignal.source = "synthetic:emg"
    out = tmp_path / "rec.csv"
    assert run_record(cfg, data_dir, seconds=2.0, out=str(out)) == OK
    assert "EMG1:emg" in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------


def test_replay_json_finds_the_scripted_gestures(cfg, data_dir, session_files, capsys):
    """A recorded session replays to detections that sit on the scripted times."""
    csv, truth = session_files
    code = run_replay(cfg, data_dir, str(csv), emg=False, blink=True, clench=True, as_json=True)
    assert code == OK
    result = json.loads(capsys.readouterr().out)
    assert result["path"] == str(csv)
    assert result["duration_s"] == pytest.approx(33.0)
    assert result["detectors"] == "double_blink, jaw_clench"
    scripted = [e for e in load_truth(truth)
                if e.kind in (EventKind.DOUBLE_BLINK, EventKind.JAW_CLENCH)]
    found = result["events"]
    assert len(found) == len(scripted) > 0
    assert set(result["counts"]) == {"double_blink", "jaw_clench"}
    assert sum(result["counts"].values()) == len(found)
    for e in found:
        assert any(e["kind"] == s.kind.value and abs(e["t"] - s.t) <= 0.3 for s in scripted)
    assert result["activations"] == len(found)
    assert result["quality"] in {"good", "degraded", "bad", "unknown"}


def test_replay_text_reports_the_false_positive_summary(cfg, data_dir, session_files, capsys):
    """The table form lists detections and ends with the proxy-labelled summary."""
    csv, _truth = session_files
    assert run_replay(cfg, data_dir, str(csv), emg=False, blink=True, clench=False) == OK
    out = capsys.readouterr().out
    assert "Replaying" in out and "double_blink" in out
    assert "Done (end of recording)" in out
    assert "False-positive summary" in out and "proxy for false positives" in out
    assert "jaw_clench" not in out.split("Detections:")[-1]      # clench switch was off


def test_replay_reads_an_npz_recorded_by_record(cfg, data_dir, tmp_path, capsys):
    """A .npz written by ``record`` replays: same duration, same channels, no failure."""
    npz = tmp_path / "copy.npz"
    assert run_record(cfg, data_dir, source="synthetic:emg", seconds=3.0, out=str(npz)) == OK
    capsys.readouterr()
    assert run_replay(cfg, data_dir, str(npz), emg=False, blink=False, clench=True,
                      as_json=True) == OK
    result = json.loads(capsys.readouterr().out)
    assert result["duration_s"] == pytest.approx(3.0)
    assert result["events"] == []


def test_replay_missing_file_is_unusable(cfg, data_dir, tmp_path, capsys):
    """A recording that is not there exits 2 with the reason."""
    assert run_replay(cfg, data_dir, str(tmp_path / "nope.csv")) == UNUSABLE
    assert "Cannot replay" in capsys.readouterr().err


def test_replay_garbage_file_is_unusable(cfg, data_dir, tmp_path, capsys):
    """A file that is not a recording is a ValueError path, exit 2."""
    bad = tmp_path / "bad.npz"
    bad.write_bytes(b"not a zip")
    code = run_replay(cfg, data_dir, str(bad))
    assert code == UNUSABLE
    assert "Cannot replay" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------


def test_evaluate_synthetic_matches_every_scripted_event(cfg, data_dir, capsys):
    """Seeded synthetic session: all scripted events found, no false positive, no miss."""
    assert run_evaluate(cfg, data_dir, seconds=33.0, seed=0, as_json=True) == OK
    result = json.loads(capsys.readouterr().out)
    overall = result["report"]["overall"]
    assert result["seed"] == 0 and result["seconds"] == 33.0
    assert result["truth_events"] == overall["true_positives"] > 0
    assert overall["false_positives"] == 0
    assert overall["false_negatives"] == 0
    assert result["report"]["false_activations"] == 0
    assert set(result["detectors"]) == {"double_blink", "jaw_clench"}
    assert result["report"]["caveat"] == CAVEAT
    assert any("not evaluated" in n for n in result["notes"])     # no calibration profile


def test_evaluate_text_ends_with_the_caveat_and_is_deterministic(cfg, data_dir, capsys):
    """Same seed, same text; the report ends with the synthetic-signal caveat."""
    outputs = []
    for _ in range(2):
        assert run_evaluate(cfg, data_dir, source="synthetic:eeg", seconds=30.0, seed=4) == OK
        outputs.append(capsys.readouterr().out)
    assert outputs[0] == outputs[1]
    assert CAVEAT in outputs[0]
    assert "Measure it on your own signal" in outputs[0]
    assert "Evaluating synthetic:eeg (seed 4)" in outputs[0]


def test_evaluate_a_labelled_recording(cfg, data_dir, session_files, capsys):
    """--file + --truth scores the recording against its labels."""
    csv, truth = session_files
    assert run_evaluate(cfg, data_dir, file=str(csv), truth=str(truth), as_json=True) == OK
    result = json.loads(capsys.readouterr().out)
    overall = result["report"]["overall"]
    assert result["source"] == f"file {csv}"
    assert result["seed"] is None
    assert overall["false_positives"] == 0 and overall["false_negatives"] == 0
    assert overall["true_positives"] == result["truth_events"] > 0
    # Squeeze labels cannot be scored without a calibration profile; that is reported.
    assert any("skipped" in n for n in result["notes"])


def test_evaluate_file_text_has_no_synthetic_hint(cfg, data_dir, session_files, capsys):
    """A labelled recording is not synthetic: no 'measure it on your own' nudge."""
    csv, truth = session_files
    assert run_evaluate(cfg, data_dir, file=str(csv), truth=str(truth)) == OK
    out = capsys.readouterr().out
    assert "Evaluating file" in out and CAVEAT in out
    assert "Measure it on your own signal" not in out


def test_evaluate_tolerance_is_honoured(cfg, data_dir, session_files, capsys):
    """A tolerance too tight for the detector's latency turns hits into FP + FN."""
    csv, truth = session_files
    assert run_evaluate(cfg, data_dir, file=str(csv), truth=str(truth), tolerance=0.001,
                        as_json=True) == OK
    overall = json.loads(capsys.readouterr().out)["report"]["overall"]
    assert overall["false_positives"] > 0 and overall["false_negatives"] > 0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"file": "MISSING"}, "Cannot read"),
        ({"file": "CSV"}, "needs its labels"),
        ({"file": "CSV", "truth": "BADTRUTH"}, "Cannot read the truth file"),
        ({"file": "CSV", "truth": "MISSING"}, "Cannot read the truth file"),
        ({"source": "brainflow:-1"}, "scores a synthetic source"),
        ({"source": "synthetic", "seconds": 10.0}, "at least"),
        ({"source": "synthetic:nonsense"}, "Cannot open source"),
        ({"emg": False, "blink": False, "clench": False}, "No detector is active"),
    ],
)
def test_evaluate_unusable_requests_exit_2(cfg, data_dir, tmp_path, session_files, capsys,
                                           kwargs, message):
    """Wrong source kind, missing labels or files, or nothing to evaluate: exit 2 with a reason."""
    csv, _truth = session_files
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    subs = {"MISSING": str(tmp_path / "nothing"), "CSV": str(csv), "BADTRUTH": str(bad)}
    kw = {key: subs.get(value, value) if isinstance(value, str) else value
          for key, value in kwargs.items()}
    assert run_evaluate(cfg, data_dir, **kw) == UNUSABLE
    assert message in capsys.readouterr().err


def test_evaluate_detector_switches_limit_what_is_scored(cfg, data_dir, capsys):
    """Turning detectors off removes their kinds from the report."""
    assert run_evaluate(cfg, data_dir, source="synthetic:eeg", seconds=30.0, emg=False,
                        clench=False, as_json=True) == OK
    result = json.loads(capsys.readouterr().out)
    assert result["detectors"] == ["double_blink"]
    assert set(result["report"]["per_kind"]) <= {"double_blink"}


# ---------------------------------------------------------------------------
# profile show / clear
# ---------------------------------------------------------------------------


def test_profile_show_without_a_profile(cfg, data_dir, capsys):
    """No file: a hint to calibrate, exit 0."""
    assert run_profile_show(cfg, data_dir) == OK
    out = capsys.readouterr().out
    assert "No calibration profile" in out and "biosignal calibrate" in out


def test_profile_show_never_prints_amplitudes_or_thresholds(cfg, data_dir, capsys):
    """Identity and age only, in text and in JSON."""
    save_profile(make_profile(), default_profile_path(data_dir))
    assert run_profile_show(cfg, data_dir) == OK
    text = capsys.readouterr().out
    assert "board='synthetic'" in text and "channels=2" in text
    assert "not printed" in text and "STALE" not in text
    assert run_profile_show(cfg, data_dir, as_json=True) == OK
    raw = capsys.readouterr().out
    payload = json.loads(raw)
    assert payload["exists"] and payload["readable"] and payload["stale"] is False
    assert payload["board_id"] == "synthetic" and payload["channels"] == ["Fp1", "EMG1"]
    assert payload["fs"] == 500.0 and payload["phases"] == ["relax", "squeeze_hard"]
    for key in ("thresholds", "baseline_rms", "noise_floor", "mvc_rms", "light_rms"):
        assert key not in payload
    for needle in AMPLITUDE_TEXT:
        assert needle not in text and needle not in raw


def test_profile_show_flags_a_stale_profile(cfg, data_dir, capsys):
    """A month-old profile is reported as stale."""
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    save_profile(make_profile(created_at=old), default_profile_path(data_dir))
    assert run_profile_show(cfg, data_dir) == OK
    assert "STALE" in capsys.readouterr().out
    run_profile_show(cfg, data_dir, as_json=True)
    assert json.loads(capsys.readouterr().out)["stale"] is True


def test_profile_show_damaged_file(cfg, data_dir, capsys):
    """A file that is not a profile is described, not parsed into a traceback."""
    default_profile_path(data_dir).write_text("{broken", encoding="utf-8")
    assert run_profile_show(cfg, data_dir) == OK
    assert "not a usable profile" in capsys.readouterr().out
    run_profile_show(cfg, data_dir, as_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["exists"] is True and payload["readable"] is False


def test_profile_show_honours_calibration_file(cfg, data_dir, tmp_path, capsys):
    """[biosignal] calibration_file points the commands at another path."""
    other = tmp_path / "elsewhere.json"
    save_profile(make_profile(), other)
    cfg.biosignal.calibration_file = str(other)
    assert run_profile_show(cfg, data_dir, as_json=True) == OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["exists"] is True and payload["path"] == str(other)


def test_profile_clear_with_yes_deletes_the_profile_and_keeps_the_counters(cfg, data_dir, capsys):
    """--yes needs no prompt; only the profile is removed."""
    path = default_profile_path(data_dir)
    save_profile(make_profile(), path)
    write_ledger(data_dir)
    assert run_profile_clear(cfg, data_dir, yes=True) == OK
    assert not path.exists()
    assert ledger_path(data_dir).exists()
    assert "Deleted" in capsys.readouterr().out


def test_profile_clear_declines_on_n(cfg, data_dir, monkeypatch, capsys):
    """Answering 'n' (or anything but yes) keeps the file and exits 0."""
    path = default_profile_path(data_dir)
    save_profile(make_profile(), path)
    monkeypatch.setattr("builtins.input", lambda *_a: "n")
    assert run_profile_clear(cfg, data_dir) == OK
    assert path.exists()
    assert "Kept" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["y", "YES", " yes "])
def test_profile_clear_accepts_a_yes_answer(cfg, data_dir, monkeypatch, answer):
    """y / yes in any case confirms."""
    path = default_profile_path(data_dir)
    save_profile(make_profile(), path)
    monkeypatch.setattr("builtins.input", lambda *_a: answer)
    assert run_profile_clear(cfg, data_dir) == OK
    assert not path.exists()


def test_profile_clear_without_an_answer_is_a_refusal(cfg, data_dir, monkeypatch, capsys):
    """EOF on stdin (a script with no --yes) deletes nothing and exits 2."""
    path = default_profile_path(data_dir)
    save_profile(make_profile(), path)

    def eof(*_a):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert run_profile_clear(cfg, data_dir) == UNUSABLE
    assert path.exists()
    assert "--yes" in capsys.readouterr().err


def test_profile_clear_with_nothing_to_clear(cfg, data_dir, capsys):
    """No profile: nothing to do, exit 0, no prompt."""
    assert run_profile_clear(cfg, data_dir) == OK
    assert "nothing to clear" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# boards
# ---------------------------------------------------------------------------


def test_boards_text_lists_the_synthetic_board(capsys):
    """The built-in generator is always listed, with its source string."""
    assert run_boards() == OK
    out = capsys.readouterr().out
    assert "synthetic" in out and "source: synthetic" in out
    assert "no hardware" in out.lower()


def test_boards_json_parses_and_has_the_synthetic_row(capsys):
    """--json is one parseable object with a complete row per board."""
    assert run_boards(as_json=True) == OK
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload["brainflow_installed"], bool)
    rows = {b["name"]: b for b in payload["boards"]}
    assert rows["synthetic"]["source"] == "synthetic"
    assert rows["synthetic"]["board_id"] is None
    assert rows["synthetic"]["serial_port_required"] is False
    for row in payload["boards"]:
        assert set(row) == {"name", "board_id", "source", "signals", "channels",
                            "serial_port_required", "notes"}
    cyton = rows["openbci-cyton"]
    assert cyton["board_id"] == 0 and cyton["source"].startswith("brainflow:0:")
    assert cyton["serial_port_required"] is True


# ---------------------------------------------------------------------------
# report and the persisted counters
# ---------------------------------------------------------------------------


def test_report_on_an_empty_ledger(cfg, data_dir, capsys):
    """No counters yet: a plain message, exit 0."""
    assert run_report(cfg, data_dir) == OK
    out = capsys.readouterr().out
    assert "No biosignal activations recorded yet" in out
    assert str(ledger_path(data_dir)) in out


def test_report_json_on_an_empty_ledger(cfg, data_dir, capsys):
    """Zero everything, and no interval to quote."""
    assert run_report(cfg, data_dir, as_json=True) == OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["activations"] == 0 and payload["cancelled"] == 0
    assert payload["cancelled_fraction_ci95"] is None
    assert payload["by_kind"] == {}
    assert payload["note"] == PROXY_NOTE


def test_report_text_from_a_stored_ledger_shows_proxy_note_and_wilson_interval(cfg, data_dir,
                                                                              capsys):
    """10 activations, 2 cancelled over 600 s: rate, interval, per-kind table and budget."""
    write_ledger(data_dir)       # double_blink 8 (2 cancelled), jaw_clench 2, 600 s, 2 sessions
    assert run_report(cfg, data_dir) == OK
    out = capsys.readouterr().out
    assert "proxy for false positives" in out
    assert "95% Wilson interval" in out and "n=10" in out
    assert "cancelled share of activations: 20%" in out
    assert "few activations, so the interval is wide" in out
    assert "sessions: 2" in out
    assert "double_blink" in out and "jaw_clench" in out
    # 2 cancelled in 600 s = 12/h against the default budget of 6/h.
    assert "cancelled per hour: 12.0" in out and "OVER" in out


def test_report_budget_verdict_within(cfg, data_dir, capsys):
    """Under the budget the verdict flips to 'within'."""
    write_ledger(data_dir, active_s=36000)
    assert run_report(cfg, data_dir) == OK
    assert "within your budget" in capsys.readouterr().out


def test_report_json_matches_the_stored_counters(cfg, data_dir, capsys):
    """JSON carries the counts, rates, the interval and the proxy note."""
    write_ledger(data_dir)
    assert run_report(cfg, data_dir, as_json=True) == OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["activations"] == 10 and payload["cancelled"] == 2
    assert payload["sessions"] == 2
    assert payload["active_seconds"] == 600.0
    assert payload["activations_per_hour"] == pytest.approx(60.0)
    assert payload["cancelled_per_hour"] == pytest.approx(12.0)
    low, high = payload["cancelled_fraction_ci95"]
    assert 0.0 <= low < 0.2 < high <= 1.0
    assert payload["note"] == PROXY_NOTE
    assert payload["budget_cancelled_per_hour"] == 6.0
    assert payload["by_kind"] == {"double_blink": {"activations": 8, "cancelled": 2},
                                  "jaw_clench": {"activations": 2, "cancelled": 0}}


@pytest.mark.parametrize("content", ["not json at all", "[1, 2, 3]", '"string"', ""])
def test_report_treats_a_corrupt_ledger_as_empty(cfg, data_dir, capsys, content):
    """A damaged counters file never crashes the report."""
    ledger_path(data_dir).write_text(content, encoding="utf-8")
    assert run_report(cfg, data_dir) == OK
    assert "No biosignal activations recorded yet" in capsys.readouterr().out


def test_load_ledger_is_zero_without_a_file(data_dir):
    """Absent file: an empty ledger."""
    stats = load_ledger(data_dir).total_stats()
    assert (stats.activations, stats.cancelled, stats.active_seconds) == (0, 0, 0)


def test_persist_session_ledger_adds_to_the_stored_totals(data_dir):
    """Each session is summed into the file; mode 0600; no temp files left behind."""
    write_ledger(data_dir)       # 10 / 2 / 600 s / 2 sessions
    session = ActivationLedger()
    session.start()
    session.record(BioEvent(EventKind.DOUBLE_BLINK, 0.0))
    session.record(BioEvent(EventKind.SQUEEZE_ON, 0.0))
    persist_session_ledger(session, data_dir)
    stored = json.loads(ledger_path(data_dir).read_text(encoding="utf-8"))
    assert stored["activations"]["double_blink"] == 9
    assert stored["activations"]["squeeze_on"] == 1
    assert stored["activations"]["jaw_clench"] == 2
    assert stored["cancelled"]["double_blink"] == 2
    assert stored["sessions"] == 3
    assert sorted(p.name for p in data_dir.iterdir()) == [LEDGER_FILENAME]
    if os.name == "posix":
        assert mode_of(ledger_path(data_dir)) == 0o600


def test_persist_session_ledger_stores_aggregates_only(data_dir):
    """The file holds counters, never an event, a timestamp or a sample."""
    session = ActivationLedger()
    session.record(BioEvent(EventKind.JAW_CLENCH, 123.456, channel="Fp1", detail={"x": 1}))
    persist_session_ledger(session, data_dir)
    stored = json.loads(ledger_path(data_dir).read_text(encoding="utf-8"))
    assert set(stored) == {"schema", "sessions", "active_seconds", "activations", "cancelled"}
    assert "123.456" not in ledger_path(data_dir).read_text(encoding="utf-8")


def test_persist_session_ledger_replaces_a_corrupt_file(data_dir):
    """Unreadable old totals are dropped, not allowed to block saving the new session."""
    ledger_path(data_dir).write_text("garbage", encoding="utf-8")
    session = ActivationLedger()
    session.record(BioEvent(EventKind.DOUBLE_BLINK, 0.0))
    persist_session_ledger(session, data_dir)
    assert load_ledger(data_dir).total_stats().activations == 1


def test_persist_session_ledger_never_raises(tmp_path):
    """An unwritable location is logged, not raised into the daemon thread."""
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    session = ActivationLedger()
    session.record(BioEvent(EventKind.DOUBLE_BLINK, 0.0))
    persist_session_ledger(session, blocker / "sub")        # parent is a file: mkdir fails
    persist_session_ledger(object(), tmp_path)              # not a ledger at all


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def test_doctor_with_synthetic_source_needs_no_hardware(cfg, data_dir, no_hardware, capsys):
    """The self-check pushes scripted blinks through the real pipeline: exit 0, no board."""
    assert run_doctor(cfg, data_dir, source="synthetic") == OK
    out = capsys.readouterr().out
    assert "YazSes biosignal doctor" in out
    assert "brainflow is not installed" in out
    assert "serial ports: none visible" in out
    assert "[OK]   scripted double blink detected" in out
    assert "[FAIL]" not in out
    assert "calibration: none" in out


def test_doctor_reports_the_calibration_without_amplitudes(cfg, data_dir, no_hardware, capsys):
    """A saved profile is described by identity and age only."""
    save_profile(make_profile(), default_profile_path(data_dir))
    assert run_doctor(cfg, data_dir, source="synthetic") == OK
    out = capsys.readouterr().out
    assert "calibration: board='synthetic'" in out
    for needle in AMPLITUDE_TEXT:
        assert needle not in out


def test_doctor_warns_about_an_unknown_source_but_still_checks_the_code_path(
        cfg, data_dir, no_hardware, capsys):
    """A typo in the source is flagged on stderr; the self-check does not need the source."""
    assert run_doctor(cfg, data_dir, source="serial:/dev/null") == OK
    assert "unknown source" in capsys.readouterr().err


def test_doctor_fails_when_the_self_check_fails(cfg, data_dir, no_hardware, monkeypatch, capsys):
    """Exit 1 is reserved for the self-check itself failing."""
    monkeypatch.setattr(cli_impl, "_self_check",
                        lambda: (False, ["  [FAIL] scripted double blink not detected"]))
    assert run_doctor(cfg, data_dir, source="synthetic") == FAILED
    assert "[FAIL]" in capsys.readouterr().out

    def boom():
        raise RuntimeError("filters broke")

    monkeypatch.setattr(cli_impl, "_self_check", boom)
    assert run_doctor(cfg, data_dir, source="synthetic") == FAILED
    assert "RuntimeError: filters broke" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# monitor
# ---------------------------------------------------------------------------


def test_monitor_synthetic_terminates_after_the_time_limit(cfg, data_dir, capsys):
    """``--source synthetic --seconds N`` runs the demo signal and stops by itself."""
    assert run_monitor(cfg, data_dir, source="synthetic", seconds=1.0, interval=0.2) == OK
    out = capsys.readouterr().out
    assert "Monitoring synthetic" in out and "Demo gestures are scripted" in out
    assert "Stopped (time limit reached)" in out
    assert "Detections:" in out and "Measured:" in out


@pytest.mark.parametrize(
    ("source", "message"),
    [("", "No source"), ("bogus", "Cannot open source"),
     ("file:/nonexistent/none.csv", "Cannot open source")],
)
def test_monitor_unusable_sources_exit_2(cfg, data_dir, capsys, source, message):
    """No source, a bad spec or a missing file is exit 2, not a hang."""
    assert run_monitor(cfg, data_dir, source=source, seconds=1.0) == UNUSABLE
    assert message in capsys.readouterr().err


def test_monitor_replays_a_file_to_its_end(cfg, data_dir, tmp_path, capsys):
    """A finite source ends the monitor with 'end of recording' and success."""
    rec = tmp_path / "short.csv"
    assert run_record(cfg, data_dir, source="synthetic:emg", seconds=2.0, out=str(rec)) == OK
    capsys.readouterr()
    assert run_monitor(cfg, data_dir, source=f"file:{rec}", seconds=20.0) == OK
    assert "Stopped (end of recording)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# the daemon adapter
# ---------------------------------------------------------------------------


class FakeRunner:
    """Stands in for BiosignalRunner: just the surface the adapter touches."""

    def __init__(self, *, persists_ledger: bool, ledger=None, fail: bool = False) -> None:
        self.persists_ledger = persists_ledger
        self.vocabulary = ["undo", "stop"]
        self.ran = 0
        self.stopped = 0
        self._fail = fail
        self._pipeline = (SimpleNamespace(_parts=SimpleNamespace(ledger=ledger))
                          if ledger is not None else None)

    def run(self) -> None:
        self.ran += 1
        if self._fail:
            raise RuntimeError("source went away")

    def stop(self) -> None:
        self.stopped += 1

    def status(self):
        return {"running": True, "n": 3}


def session_ledger() -> ActivationLedger:
    ledger = ActivationLedger()
    ledger.start()
    ledger.record(BioEvent(EventKind.DOUBLE_BLINK, 0.0))
    return ledger


def test_adapter_saves_the_ledger_when_the_runner_does_not(data_dir):
    """persists_ledger False: the adapter writes this session's counters on the way out."""
    runner_ = FakeRunner(persists_ledger=False, ledger=session_ledger())
    BiosignalActivationSource(runner_, data_dir).run()
    assert runner_.ran == 1
    stored = json.loads(ledger_path(data_dir).read_text(encoding="utf-8"))
    assert stored["activations"] == {"double_blink": 1}
    assert stored["sessions"] == 1


def test_adapter_does_not_save_again_when_the_runner_persists_its_own(data_dir):
    """persists_ledger True: a second writer would count the session twice, so it stays out."""
    runner_ = FakeRunner(persists_ledger=True, ledger=session_ledger())
    BiosignalActivationSource(runner_, data_dir).run()
    assert runner_.ran == 1
    assert not ledger_path(data_dir).exists()


def test_adapter_saves_even_when_the_runner_raises(data_dir):
    """A crash in the runner still keeps the counters gathered so far."""
    runner_ = FakeRunner(persists_ledger=False, ledger=session_ledger(), fail=True)
    adapter = BiosignalActivationSource(runner_, data_dir)
    with pytest.raises(RuntimeError, match="source went away"):
        adapter.run()
    assert load_ledger(data_dir).total_stats().activations == 1
    adapter.stop()                       # must not block for the full wait: run() is over


def test_adapter_without_a_pipeline_or_ledger_saves_nothing(data_dir):
    """A runner that never built a pipeline leaves no file behind."""
    BiosignalActivationSource(FakeRunner(persists_ledger=False), data_dir).run()
    assert not ledger_path(data_dir).exists()
    bare = FakeRunner(persists_ledger=False)
    bare._pipeline = SimpleNamespace(_parts=SimpleNamespace(ledger=None))
    BiosignalActivationSource(bare, data_dir).run()
    assert not ledger_path(data_dir).exists()


def test_adapter_delegates_stop_status_and_vocabulary(data_dir):
    """The HotkeyBackend-style surface passes straight through to the runner."""
    runner_ = FakeRunner(persists_ledger=True)
    adapter = BiosignalActivationSource(runner_, data_dir)
    assert adapter.vocabulary == ("undo", "stop")
    assert adapter.status() == {"running": True, "n": 3}
    adapter.stop()
    assert runner_.stopped == 1


def test_adapter_note_cancelled_forwards_to_the_pipeline(data_dir):
    """A non-switch undo is reported to the pipeline; failures and absence are False."""
    runner_ = FakeRunner(persists_ledger=True)
    adapter = BiosignalActivationSource(runner_, data_dir)
    assert adapter.note_cancelled() is False              # no pipeline yet
    runner_._pipeline = SimpleNamespace(note_cancelled=lambda: True)
    assert adapter.note_cancelled() is True

    def explode():
        raise RuntimeError("boom")

    runner_._pipeline = SimpleNamespace(note_cancelled=explode)
    assert adapter.note_cancelled() is False
    runner_._pipeline = SimpleNamespace()                 # a pipeline with no such method
    assert adapter.note_cancelled() is False
