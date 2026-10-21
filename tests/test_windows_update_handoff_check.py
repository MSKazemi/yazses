"""The real-Windows proof of ADR-027's hand-off: the driver, and the CI job that runs it.

`scripts/check_windows_update_handoff.py` runs the detached PowerShell job for real on a
Windows runner. Its Windows half cannot execute here; what can is pinned:

* its `--plan-only` half runs on any OS and passes -- the fake release, the real fetch,
  download and SHA-256 check over a real socket;
* that half FAILS on the defect the first version shipped with (the release API asked
  for `application/octet-stream`, which api.github.com answers with 415), so the fake
  server is strict where GitHub is strict and not a second injected opener;
* the Windows half refuses to run off Windows instead of passing vacuously;
* `test.yml` runs it on `windows-latest`, as an advisory job that `ci-gate` does not need
  (tests/test_ci_gate.py derives that contract from the file).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_windows_update_handoff.py"
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
JOB = "windows-update-handoff"


@pytest.fixture()
def driver():
    spec = importlib.util.spec_from_file_location("check_windows_update_handoff", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plan_only_passes(driver, capsys):
    assert driver.main(["--plan-only"]) == 0
    out = capsys.readouterr().out
    assert "0 failed" in out and "FAIL" not in out


def test_plan_only_catches_the_415_header_defect(driver, monkeypatch, capsys):
    # The defect that every injected-opener test missed: JSON endpoint, binary Accept.
    monkeypatch.setattr(driver.iu, "request_headers", lambda url: dict(driver.iu._ASSET_HEADERS))
    assert driver.main(["--plan-only"]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_the_fake_release_refuses_the_wrong_media_type_like_github(driver):
    import urllib.error
    import urllib.request

    release = driver.FakeRelease(b"MZ installer")
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{release.port}{driver.API_PATH}",
            headers={"Accept": "application/octet-stream"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with pytest.raises(urllib.error.HTTPError) as err:
            opener.open(request, timeout=10)
        assert err.value.code == 415
    finally:
        release.close()


@pytest.mark.skipif(sys.platform == "win32", reason="the Windows half runs in CI")
def test_the_windows_half_refuses_to_run_elsewhere(driver, capsys):
    assert driver.main([]) == 2
    assert "--plan-only" in capsys.readouterr().err


def _job() -> dict:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    assert JOB in jobs, f"test.yml has no {JOB} job"
    return jobs[JOB]


def test_ci_runs_the_hand_off_on_windows():
    job = _job()
    assert job["runs-on"] == "windows-latest"
    assert isinstance(job.get("timeout-minutes"), int) and job["timeout-minutes"] <= 30
    runs = " ".join(step.get("run", "") for step in job["steps"])
    assert "scripts/check_windows_update_handoff.py" in runs
    assert "--plan-only" not in runs  # the real thing, not the any-OS half


def test_the_new_job_is_advisory_until_proven():
    # CI_POLICY.md section 9: a never-run cross-OS job must not turn main red on its
    # first PR. Advisory means a literal `continue-on-error: true` and not a gate need.
    job = _job()
    assert job.get("continue-on-error") is True
    gate = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["ci-gate"]
    assert JOB not in gate["needs"]
    text = WORKFLOW.read_text(encoding="utf-8")
    # The comment directly above the job writes the reason and promotion condition down.
    above = text.split(f"\n  {JOB}:", 1)[0].rsplit("\n\n", 1)[-1]
    assert "PROMOTE" in above and "never run" in above


def test_a_powershell_log_with_a_byte_order_mark_is_read_and_printable(driver, tmp_path):
    """The first real windows-latest run crashed here, not in the hand-off.

    Windows PowerShell 5.1's `-Encoding UTF8` writes a BOM; reading update.log as plain
    utf-8 kept U+FEFF, and printing it to the runner's cp1252 console raised
    UnicodeEncodeError after the hand-off itself had started fine (run 39566671404).
    """
    log = tmp_path / "update.log"
    log.write_bytes("﻿[2026-10-21] waiting for YazSes to exit — ç\n".encode("utf-8"))
    text = driver._read(log)
    assert not text.startswith("﻿")
    assert text.startswith("[2026-10-21]")
    text.encode("cp1252", errors="strict")  # what the runner's console can print
