"""`yazses doctor --strict` and `--json`: usable from a script, and safe to paste.

The default is unchanged: the text report, and exit code 0 even when a line is FAIL.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.system import doctor

runner = CliRunner()

SECRET = "Zed Private Headset"

_FAILING = [
    ("Platform", "OK", "linux"),
    ("  xdotool", "SKIP", "not needed on this session type"),
    ("Daemon", "WARN", "not running"),
    ("Input device", "FAIL", f"pinned: {SECRET!r}"),
]
_WARNING = [row for row in _FAILING if row[1] != "FAIL"]


@pytest.fixture
def rows(monkeypatch):
    """Replace the checks; returns a function that sets the rows and records the calls."""
    calls: list[dict] = []

    def install(checks):
        def fake(check_mic=False, mic_seconds=2.0, *, emit=True):
            calls.append({"check_mic": check_mic, "emit": emit})
            if emit:
                print("YazSes doctor (test):")
            else:
                print("a probed library being chatty")
            return list(checks)

        monkeypatch.setattr(doctor, "run_doctor", fake)
        return calls

    return install


# -- the pure half --------------------------------------------------------------


def test_only_a_fail_row_is_a_failure() -> None:
    assert doctor.has_failure(_FAILING)
    assert not doctor.has_failure(_WARNING)
    assert not doctor.has_failure([])


def test_the_object_counts_and_names_every_row() -> None:
    report = doctor.json_report(_FAILING, "linux")
    assert report["schema_version"] == 1
    assert report["platform"] == "linux"
    assert isinstance(report["yazses"], str) and report["yazses"]
    assert report["result"] == "fail"
    assert report["counts"] == {"ok": 1, "warn": 1, "fail": 1, "skip": 1}
    assert report["checks"] == [
        {"name": "Platform", "status": "OK"},
        {"name": "xdotool", "status": "SKIP"},
        {"name": "Daemon", "status": "WARN"},
        {"name": "Input device", "status": "FAIL"},
    ]


@pytest.mark.parametrize(
    ("checks", "result"),
    [
        (_WARNING, "warn"),
        ([("Platform", "OK", "x"), ("Update check", "SKIP", "off")], "ok"),
    ],
)
def test_the_result_is_the_worst_status(checks, result) -> None:
    assert doctor.json_report(checks, "linux")["result"] == result


def test_no_row_detail_reaches_the_object() -> None:
    assert SECRET not in json.dumps(doctor.json_report(_FAILING, "linux"))


# -- the real run ---------------------------------------------------------------


def test_a_real_run_prints_nothing_when_asked_and_leaks_no_config_value(
    sandbox_paths, capsys
) -> None:
    """Row *names* are the only text that leaves, so no user value may be in one."""
    sandbox_paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    sandbox_paths.config_file.write_text(
        '[audio]\ndevice = "Zed Private Headset"\n'
        '[emg]\nble_address = "AA:BB:CC:DD:EE:FF"\n'
        '[stt]\nengine = "zed-private-engine"\nmodel = "/zed/private/model"\n'
        '[accessibility]\nvad_threshold = "zed-private-threshold"\n',
        encoding="utf-8",
    )
    checks = doctor.run_doctor(emit=False)
    assert capsys.readouterr().out == ""
    names = {name.strip() for name, _status, _detail in checks}
    assert {"Platform", "Config file", "Config validity"} <= names
    # The values are in the human report's details, which is why those are left out.
    assert any("AA:BB:CC:DD:EE:FF" in detail for _name, _status, detail in checks)
    text = json.dumps(doctor.json_report(checks, "linux")).lower()
    for value in ("zed private", "zed-private", "/zed/private", "aa:bb:cc",
                  str(sandbox_paths.config_dir).lower()):
        assert value not in text


# -- the command ----------------------------------------------------------------


def test_by_default_a_failing_run_still_exits_zero(rows) -> None:
    calls = rows(_FAILING)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "YazSes doctor" in result.stdout
    assert calls == [{"check_mic": False, "emit": True}]


def test_strict_exits_one_on_a_fail_and_keeps_the_report(rows) -> None:
    rows(_FAILING)
    result = runner.invoke(cli.app, ["doctor", "--strict"])
    assert result.exit_code == 1, result.output
    assert "YazSes doctor" in result.stdout


def test_strict_ignores_warnings(rows) -> None:
    rows(_WARNING)
    result = runner.invoke(cli.app, ["doctor", "--strict"])
    assert result.exit_code == 0, result.output


def test_json_is_the_only_thing_on_stdout(rows) -> None:
    calls = rows(_FAILING)
    result = runner.invoke(cli.app, ["doctor", "--json", "--mic"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["result"] == "fail"
    assert SECRET not in result.stdout
    assert calls == [{"check_mic": True, "emit": False}]


def test_json_and_strict_combine(rows) -> None:
    rows(_FAILING)
    result = runner.invoke(cli.app, ["doctor", "--json", "--strict"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["counts"]["fail"] == 1
