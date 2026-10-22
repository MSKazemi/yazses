"""No home path survives into `yazses report`, read through the command itself (SEC-001).

`test_report.py` pins `redact_text` and the log tail one function at a time. What nothing
checked is the **bundle the command produces**: every field `collect()` assembles, through
`yazses report --print` and the file `yazses report -o` writes. Fields are added to that
bundle one at a time, by different changes, and the redactors only protect the fields that
are routed through them -- `report.py`'s own history is three fields that were not (the
daemon block, the free-text keys, every list).

Doing it end to end found three more. Each carried the home directory into a file the user
is invited to attach to a public issue:

* `config_problems` was bare `str(p)`, and a problem quotes the value it refused: a
  mistyped `vad_threshold = "/home/<you>/v"` was `~/v` in the config section and
  `got the text "/home/<you>/v"` in the problems.
* A config file that could not be read put its full path into both `config.error` and
  `config_problems` (`[Errno 13] Permission denied: '/home/<you>/…/config.toml'`).
* A log that could not be read put its full path into `log_tail`.

## Why the home directory is `tmp_path` here

`report._HOME` is compiled from `Path.home()` at import. Writing fixtures *under* the real
home would make the test depend on, and write into, the developer's own account -- this
repo has lost a release to a test that read the host. So the test points the home pattern
at `tmp_path` and puts every fixture there: the redactor is the code under test, and which
directory it is told is "home" is configuration. The account name is pinned the same way,
to `ada`, never read from `getpass`.

The output is parsed and walked rather than searched as text: JSON escapes a Windows
path's backslashes, so a substring search of the raw output would pass on the very
platform where a path is longest.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from yazses.system import report as report_mod


def _strings(node):
    """Every string anywhere in a parsed report: keys and values."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(node, list | tuple):
        for v in node:
            yield from _strings(v)
    elif isinstance(node, str):
        yield node


def _leaks(report: dict, home: Path) -> list[str]:
    # The account on word boundaries, as the redactor matches it: "unreadable" and
    # "readable" both contain `ada`.
    account = re.compile(r"\bada\b", re.IGNORECASE)
    paths = {str(home), str(home).replace("\\", "/")}
    return [
        s for s in _strings(report)
        if any(p in s for p in paths) or account.search(s)
    ]


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """`tmp_path` plays the home directory; `ada` plays the account."""
    monkeypatch.setattr(report_mod, "_HOME", re.compile(re.escape(str(tmp_path))))
    monkeypatch.setattr(report_mod, "_ACCOUNT", re.compile(r"\bada\b", re.IGNORECASE))
    return tmp_path


def _toml_str(path: Path) -> str:
    """A TOML basic string for *path* -- backslashes escaped, so Windows paths parse."""
    return json.dumps(str(path))


def _write_fixtures(home: Path) -> SimpleNamespace:
    cfg_dir = home / ".config" / "yazses"
    data_dir = home / ".local" / "share" / "yazses"
    log_dir = home / ".local" / "state" / "yazses" / "log"
    for d in (cfg_dir, data_dir, log_dir):
        d.mkdir(parents=True)
    h = home
    (cfg_dir / "config.toml").write_text(
        "\n".join([
            "[stt]",
            f"model = {_toml_str(h / 'models' / 'whisper-small')}",
            f"initial_prompt = {_toml_str(h / 'notes')}",
            "[audio]",
            f"device = {_toml_str(h / 'mic')}",
            "[accessibility]",
            # Mistyped on purpose: a string where a number belongs is a config problem,
            # and the problem quotes the value it refused.
            f"vad_threshold = {_toml_str(h / 'v')}",
            "[remote]",
            f"key_file = {_toml_str(h / '.ssh' / 'id_ed25519')}",
            f"ssh_port = {_toml_str(h / 'port')}",
            "[learning]",
            f"redact_patterns = [{_toml_str(h / 'secret')}]",
            "",
        ]),
        encoding="utf-8",
    )
    (log_dir / "daemon.log").write_text(
        "\n".join([
            f"2026-10-21 10:00:00,000 INFO yazses.core.daemon: config at {h / 'cfg'}",
            "2026-10-21 10:00:01,000 WARNING yazses.audio: mic named ada's AirPods",
            "2026-10-21 10:00:02,000 ERROR yazses.core.daemon: Pipeline error",
            "Traceback (most recent call last):",
            f'  File "{h / "venv" / "daemon.py"}", line 1, in run',
            f"FileNotFoundError: {h / 'missing.wav'}",
            "/media/ada/USB-STICK/note.wav was transcribed",
            "",
        ]),
        encoding="utf-8",
    )
    return SimpleNamespace(
        config_file=cfg_dir / "config.toml",
        log_dir=log_dir,
        data_dir=data_dir,
        ipc_socket=home / ".run" / "yazses.sock",
    )


class _Client:
    def __init__(self, home: Path) -> None:
        self._home = home

    def call(self, method, **_kw):
        assert method == "status"
        return {
            "state": "idle",
            "last_error": f"FileNotFoundError: {self._home / 'private' / 'keys.txt'}",
            "input_device": "ada's AirPods Pro",
            "model": str(self._home / "models" / "whisper-small"),
        }


def _run_report(monkeypatch, home: Path, *args: str):
    from yazses import cli

    paths = _write_fixtures(home)
    platform = SimpleNamespace(paths=paths, ipc_client_factory=lambda _sock: _Client(home))
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    return CliRunner().invoke(cli.app, ["report", *args], env={"COLUMNS": "200"}), paths


def test_yazses_report_print_carries_no_home_path(home, monkeypatch):
    result, _ = _run_report(monkeypatch, home, "--print")

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    # The fixtures reached the bundle at all -- otherwise "no leak" is about nothing.
    assert report["daemon"]["state"] == "idle"
    assert report["config"]["stt"]["model"].startswith("~"), report["config"]["stt"]
    assert any("vad_threshold" in p for p in report["config_problems"])
    assert any("Traceback" in line for line in report["log_tail"])
    assert _leaks(report, home) == []


def test_the_written_bundle_carries_no_home_path(home, monkeypatch):
    out = home / "elsewhere" / "report.json"
    result, _ = _run_report(monkeypatch, home, "-o", str(out))

    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["config_problems"], "no problems were collected; the fixture is wrong"
    assert _leaks(report, home) == []


def test_a_mistyped_value_is_shown_as_the_config_section_shows_it(home, monkeypatch):
    """The problem quotes `~/v`, exactly as `config.accessibility.vad_threshold` does."""
    result, _ = _run_report(monkeypatch, home, "--print")
    report = json.loads(result.output)

    shown = report["config"]["accessibility"]["vad_threshold"]
    problem = next(p for p in report["config_problems"] if "vad_threshold" in p)
    assert shown.startswith("~"), shown
    assert f'"{shown}"' in problem, problem


def test_a_mistyped_identifier_is_not_quoted_back(home, monkeypatch):
    """`redact_config` blanks `[remote] ssh_port`'s text, so its problem must not quote it."""
    result, _ = _run_report(monkeypatch, home, "--print")
    report = json.loads(result.output)

    assert report["config"]["remote"]["ssh_port"] == "<redacted>"
    problem = next(p for p in report["config_problems"] if "ssh_port" in p)
    assert '"<redacted>"' in problem, problem
    assert "port" not in problem.split("ssh_port", 1)[1], problem


def test_unreadable_config_and_log_do_not_leak_their_paths(home):
    """An OSError's message is the path it could not open, and that path is under $HOME.

    Both are made unreadable by being directories, which raises on every platform and
    for every user -- `chmod 000` does neither on Windows or as root.
    """
    config = home / ".config" / "yazses" / "config.toml"
    log = home / ".local" / "state" / "yazses" / "log" / "daemon.log"
    config.mkdir(parents=True)
    log.mkdir(parents=True)

    report = report_mod.collect(
        config_file=config, log_file=log, data_dir=home, status=None,
    )

    assert "unreadable" in report["config"]["error"], report["config"]
    assert report["log_tail"][0].startswith("<unreadable"), report["log_tail"]
    assert _leaks(report, home) == []


def test_an_invalid_redact_pattern_is_not_quoted_into_the_report(home):
    """`[learning] redact_patterns` is the user's description of their own secrets.

    `redact_config` summarises it by size; `configcheck` quotes an invalid entry by
    `repr`. The problem has to follow the config section, not the validator.
    """
    config = home / "config.toml"
    config.write_text(
        '[learning]\nredact_patterns = ["acct-(\\\\d{4}"]\n', encoding="utf-8"
    )

    report = report_mod.collect(
        config_file=config, log_file=home / "absent.log", data_dir=home, status=None,
    )

    problems = [p for p in report["config_problems"] if "redact_patterns" in p]
    assert problems, report["config_problems"]
    assert not any("acct" in p for p in problems), problems
    assert "acct" not in json.dumps(report)


@pytest.mark.parametrize(
    ("detail", "key", "raw", "expected"),
    [
        # An ordinary setting keeps its quoted value: it is the diagnosis.
        ('should be a number, got the text "0.004"', "vad_threshold",
         {"accessibility": {"vad_threshold": "0.004"}}, '"0.004"'),
        # An identifier does not, even with no raw config to consult.
        ('should be a whole number, got the text "lab.example.com"', "ssh_port",
         None, '"<redacted>"'),
    ],
)
def test_redact_problem_follows_redact_config(detail, key, raw, expected):
    from yazses.configcheck import ConfigProblem

    section = "accessibility" if key == "vad_threshold" else "remote"
    out = report_mod.redact_problem(ConfigProblem(section, key, detail, False), raw)
    assert expected in out, out


# --- SEC-004: what `yazses report` reads, writes and sends -------------------------------

PRIVACY = Path(__file__).resolve().parents[1] / "docs" / "privacy-statement.md"

#: Each top-level key `collect()` produces, and the row of the privacy statement's
#: "Bug reports" table that accounts for it. A new key fails the build until the page
#: says where it comes from -- the page is the user's only description of the file.
_DOCUMENTED_SOURCE = {
    "generated_by": None,  # a constant string
    "system": "your system",
    "daemon": "the running daemon",
    "config": "`config.toml`",
    "config_problems": "`config.toml`",
    "log_tail": "`daemon.log`",
    "corpus": "`corpus.db` and `clips/`",
}


def _bug_report_section() -> str:
    text = PRIVACY.read_text(encoding="utf-8")
    start = text.index("## Bug reports (`yazses report`)")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_every_part_of_the_bundle_is_accounted_for_on_the_privacy_page(home, monkeypatch):
    result, _ = _run_report(monkeypatch, home, "--print")
    keys = set(json.loads(result.output))

    assert keys == set(_DOCUMENTED_SOURCE), (
        f"`collect()` now produces {sorted(keys - set(_DOCUMENTED_SOURCE))} and no longer "
        f"produces {sorted(set(_DOCUMENTED_SOURCE) - keys)}. Add or remove the row in "
        "docs/privacy-statement.md's 'Bug reports' table, then update this map."
    )
    rows = [line for line in _bug_report_section().splitlines() if line.startswith("| ")]
    for key, label in _DOCUMENTED_SOURCE.items():
        if label is not None:
            assert any(row.startswith(f"| {label} |") for row in rows), (key, label)


def test_yazses_report_writes_one_file_and_opens_nothing(home, monkeypatch):
    """The page says: one file, no browser, no connection. Hold the command to it.

    The browser is the only way any part of `system/report.py` reaches the network
    (ADR-019 lists the issue URL under handoff, used by the daemon's toast button), so a
    tripwire on `open_url` is what would notice the command growing that path.
    """
    from yazses import cli

    opened: list[str] = []
    monkeypatch.setattr(
        "yazses.system.browser.open_url", lambda url, *_a, **_k: opened.append(url)
    )
    paths = _write_fixtures(home)
    platform = SimpleNamespace(paths=paths, ipc_client_factory=lambda _sock: _Client(home))
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    out = home / "out" / "report.json"
    before = {p for p in home.rglob("*") if p.is_file()}

    printed = CliRunner().invoke(cli.app, ["report", "--print"], env={"COLUMNS": "200"})
    after_print = {p for p in home.rglob("*") if p.is_file()}
    written = CliRunner().invoke(cli.app, ["report", "-o", str(out)], env={"COLUMNS": "200"})
    after_write = {p for p in home.rglob("*") if p.is_file()}

    assert printed.exit_code == 0, printed.output
    assert written.exit_code == 0, written.output
    assert after_print == before, f"--print wrote {sorted(after_print - before)}"
    assert after_write - before == {out}, f"-o wrote {sorted(after_write - before)}"
    assert opened == [], f"`yazses report` opened a browser: {opened}"
    assert "Nothing was sent anywhere" in written.output
