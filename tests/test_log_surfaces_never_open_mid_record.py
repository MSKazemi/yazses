"""Both surfaces that show the daemon log must respect record boundaries.

One root cause produced two separate defects. `yazses logs` sliced `content[-lines:]` and
opened on an orphaned traceback fragment -- no timestamp, no level, misattributed to the
newest failure. `yazses report` filtered lines containing " DEBUG ", removed the only line
of a record carrying the level, and emitted the body of a record it had just judged unsafe
to attach to a public issue.

Both are fixed. This tests the *property* at both exits rather than the two fixes, and
pins the set of surfaces so a third one cannot be added without being covered -- the
region is derived from the source, not listed here.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from yazses.system.logtail import starts_record

REPO = pathlib.Path(__file__).resolve().parents[1]

TRACEBACK = [
    "Traceback (most recent call last):",
    '  File "/x/sounddevice.py", line 834, in __init__',
    "    _get_stream_parameters(kind, device, channels)",
    "  File \"/x/sounddevice.py\", line 578, in query_devices",
    "    raise PortAudioError(f'Error querying device {device}')",
    "sounddevice.PortAudioError: Error querying device -1",
]


def _log_lines() -> list[str]:
    """A log whose records are deliberately of different lengths.

    The multi-line records sit at different depths from the end, so *some* window size
    lands inside each of them -- which `test_the_fixture_really_straddles_a_record`
    proves rather than assumes.
    """
    out: list[str] = []
    for i in range(6):
        out.append(f"2026-08-24 10:00:0{i},000 INFO yazses.core.daemon: burst {i}")
    out.append("2026-08-24 10:00:07,000 ERROR yazses.core.daemon: Re-calibrate action failed")
    out += TRACEBACK
    out.append("2026-08-24 10:00:08,000 INFO yazses.core.daemon: Recording started")
    out.append("2026-08-24 10:00:09,000 ERROR yazses.core.daemon: capture failed")
    out += TRACEBACK
    out.append("2026-08-24 10:00:10,000 INFO yazses.core.daemon: done")
    return out


def _write_log(dirpath: pathlib.Path) -> pathlib.Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    log = dirpath / "daemon.log"
    log.write_text("\n".join(_log_lines()) + "\n", encoding="utf-8")
    return log


def test_the_fixture_really_straddles_a_record() -> None:
    """Without this, every assertion below could hold for the wrong reason."""
    lines = _log_lines()
    straddling = [n for n in range(1, len(lines)) if not starts_record(lines[len(lines) - n])]
    assert len(straddling) >= 8, (
        f"only {len(straddling)} window sizes open mid-record -- the fixture does not "
        f"exercise the defect"
    )


# --- exit 1: `yazses logs` ----------------------------------------------------------


def test_yazses_logs_never_opens_mid_record(sandbox_paths, capsys) -> None:
    from yazses.cli import logs
    from yazses.platform import get_paths

    _write_log(get_paths().log_dir)
    for n in range(1, len(_log_lines()) + 3):
        logs(lines=n, path_only=False)
        printed = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        body = [ln for ln in printed if not ln.startswith("(")]
        assert body, f"n={n} printed nothing"
        note = [ln for ln in printed if ln.startswith("(") and "record" in ln]
        assert starts_record(body[0]) or note, (
            f"n={n}: output opens mid-record with no explanation: {body[0]!r}"
        )


# --- exit 2: `yazses report`'s bundled tail -----------------------------------------


def test_the_report_tail_never_opens_mid_record(tmp_path) -> None:
    from yazses.system import report as report_mod

    log = _write_log(tmp_path / "log")
    for n in range(1, len(_log_lines()) + 3):
        tail = report_mod._log_tail(log, n)
        body = [ln for ln in tail if not ln.startswith("<")]
        assert body, f"n={n} produced no lines"
        assert starts_record(body[0]), (
            f"n={n}: the bundled tail opens mid-record: {body[0]!r}"
        )


def test_the_report_tail_never_emits_a_dropped_records_body(tmp_path) -> None:
    from yazses.system import report as report_mod

    lines = _log_lines()
    lines.insert(-1, "2026-08-24 10:00:09,500 DEBUG yazses.core.daemon: 'a private sentence'")
    lines[-1:-1] = ["  continuation of the DEBUG record"]
    log = tmp_path / "log" / "daemon.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for n in range(1, len(lines) + 3):
        joined = "\n".join(report_mod._log_tail(log, n))
        assert "a private sentence" not in joined, f"n={n} leaked the DEBUG record"
        assert "continuation of the DEBUG record" not in joined, f"n={n} leaked its body"


# --- the region is derived, so a third surface cannot slip in -----------------------


def _modules_reading_the_daemon_log() -> set[str]:
    """Every module that names the daemon log file, read out of the source."""
    found = set()
    for path in sorted((REPO / "src" / "yazses").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if re.search(r'"daemon\.log"|\'daemon\.log\'', line):
                found.add(path.relative_to(REPO).as_posix())
    return found


#: Why each module that names the log file is accounted for. The *set* is derived from
#: the source; only the justification is written down, because a reason cannot be
#: derived. A module that appears here without an entry fails the build.
_ACCOUNTED = {
    "src/yazses/cli.py":
        "`yazses logs` reads it through `logtail.tail_records`, and passes the same path "
        "to `report.collect` as `log_file=`.",
    "src/yazses/core/daemon.py":
        "Two references, neither a reader that slices: `_configure_logging` *writes* the "
        "file via RotatingFileHandler, and `_handle_prepare_report` passes the path to "
        "`report.collect`, i.e. through the same `_log_tail` covered above.",
}


def test_every_module_naming_the_log_file_is_accounted_for() -> None:
    """A third reader must either use `logtail` or be explained here.

    Not a convenience list: this is the check that the tests above are *complete*.
    `system/report.py` is reached through the `log_file=` argument its callers pass, so
    it never names the file itself -- which is exactly why the set alone is not enough.
    """
    derived = _modules_reading_the_daemon_log()
    assert derived, "the scan found no module naming daemon.log -- it is broken"
    unexplained = derived - set(_ACCOUNTED)
    assert not unexplained, (
        f"{sorted(unexplained)} name daemon.log and nothing here says why -- either route "
        f"them through yazses.system.logtail and extend the tests above, or add a reason"
    )
    stale = set(_ACCOUNTED) - derived
    assert not stale, f"{sorted(stale)} no longer name daemon.log; drop the entry"


def test_the_prepared_issue_body_never_carries_a_dropped_records_body(tmp_path) -> None:
    """The severest path: a toast button that opens a prefilled *public* issue.

    `_handle_prepare_report` -> `report.collect` -> `summarise_for_issue` ->
    `_render_issue_body` -> `issue_url` -> the browser. Before the record-level filter,
    the body of a DEBUG record whose header had been dropped travelled all the way into
    that form.
    """
    from yazses.system import report as report_mod

    lines = _log_lines()
    lines.insert(-1, "2026-08-24 10:00:09,500 DEBUG yazses.core.daemon: 'a private sentence'")
    lines.insert(-1, "  continuation carrying more of it")
    log = tmp_path / "log" / "daemon.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    gathered = report_mod.collect(
        config_file=tmp_path / "absent.toml", log_file=log, data_dir=tmp_path,
        status=None, log_lines=200,
    )
    body = report_mod.summarise_for_issue(gathered, log_lines=200)
    url = report_mod.issue_url("crash", body)
    for leak in ("a private sentence", "continuation carrying more of it"):
        assert leak not in body, f"the issue body carries {leak!r}"
        assert leak.replace(" ", "%20") not in url and leak not in url


@pytest.mark.parametrize("module", ["src/yazses/cli.py", "src/yazses/system/report.py"])
def test_both_surfaces_go_through_the_shared_primitive(module: str) -> None:
    text = (REPO / module).read_text(encoding="utf-8")
    assert "yazses.system.logtail" in text, f"{module} no longer uses the shared primitive"
    assert "content[-lines:]" not in text, f"{module} went back to a blind slice"
