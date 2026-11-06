"""Two platform-page statements that had drifted from the code and the release record.

1. `docs/validation-matrix.md` told the next Mac tester that the first-run
   permission-prompt fix (#562, #578) was "on main and not yet released". The
   CHANGELOG records it under a released heading (v2.44.0), so a tester following the
   page could not tell which build to try. The page must not call a released fix
   unreleased, and must name the release that carries it.

2. `docs/install-cost.md` said logs and the PID file live in `~/.local/share/yazses/`.
   On Linux, `platform/linux/paths.py` takes the log directory from platformdirs'
   `user_log_dir` (`~/.local/state/yazses/log`) and the PID file from the runtime
   directory (`$XDG_RUNTIME_DIR/yazses/daemon.pid`, via `Paths.pid_file`). Someone
   cleaning up by that table would delete the wrong directory and keep the log.

Both checks read the source of truth rather than a hand-written answer: the
CHANGELOG heading for (1), platformdirs' Unix implementation for (2).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / "docs" / "validation-matrix.md"
COST = ROOT / "docs" / "install-cost.md"
CHANGELOG = ROOT / "CHANGELOG.md"

FIX_HEADING = "### Fixed — macOS: no Accessibility or microphone prompt was ever raised"


def _release_holding(heading: str) -> str:
    """The `## [x]` section a CHANGELOG heading sits under, e.g. '2.44.0' or 'Unreleased'."""
    current = None
    for line in CHANGELOG.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## \[([^\]]+)\]", line)
        if m:
            current = m.group(1)
        elif line.startswith(heading):
            assert current is not None, "fix heading appears before any release heading"
            return current
    pytest.fail(f"CHANGELOG no longer has the heading {heading!r}; update this test")


def _macos_apple_silicon_dmg_row() -> str:
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        if line.startswith("| **Apple silicon, `.dmg`** |"):
            return line
    pytest.fail("validation matrix lost its Apple silicon .dmg row")


def test_matrix_does_not_call_the_released_first_run_fix_unreleased():
    release = _release_holding(FIX_HEADING)
    row = _macos_apple_silicon_dmg_row()
    if release == "Unreleased":
        pytest.skip("the fix is genuinely unreleased; the old wording would be true")
    assert "not yet released" not in row, (
        f"the #562/#578 first-run fix shipped in v{release}, "
        "but the matrix row still calls it unreleased"
    )
    assert f"v{release}" in row, f"the next-tester note should name v{release}"


def _table_rows(text: str) -> list[list[str]]:
    return [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in text.splitlines()
        if line.startswith("| ")
    ]


def test_install_cost_names_the_real_linux_log_and_pid_locations(monkeypatch):
    unix = pytest.importorskip("platformdirs.unix")
    for var in ("XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(var, raising=False)
    dirs = unix.Unix(appname="yazses", appauthor=False, ensure_exists=False)
    home = Path("~").expanduser()
    log_rel = Path(dirs.user_log_dir).relative_to(home).as_posix()
    data_rel = Path(dirs.user_data_dir).relative_to(home).as_posix()
    assert log_rel.startswith(".local/state/yazses")  # sanity: what the page should say
    assert data_rel == ".local/share/yazses"

    rows = _table_rows(COST.read_text(encoding="utf-8"))
    data_rows = [r for r in rows if f"~/{data_rel}" in r[0]]
    assert data_rows, "install-cost.md lost its data-directory row"
    for r in data_rows:
        why = " ".join(r[1:]).lower()
        assert "log" not in why, f"logs are not in ~/{data_rel}: {r}"
        assert "pid" not in why, f"the PID file is not in ~/{data_rel}: {r}"

    assert any("~/.local/state/yazses" in r[0] for r in rows), (
        "install-cost.md does not say where the diagnostic log is written"
    )
    assert any("XDG_RUNTIME_DIR" in r[0] and "PID" in r[0] for r in rows), (
        "install-cost.md does not say where the PID file is written"
    )


def test_linux_paths_still_take_logs_and_pid_from_where_the_page_says():
    """Pin the code side, so a move in paths.py re-opens the page instead of passing."""
    src = (ROOT / "src" / "yazses" / "platform" / "linux" / "paths.py").read_text(
        encoding="utf-8"
    )
    assert "log_dir=Path(dirs.user_log_dir)" in src
    assert "dirs.user_runtime_dir" in src
    base = (ROOT / "src" / "yazses" / "platform" / "base.py").read_text(encoding="utf-8")
    assert 'self.state_dir / "daemon.pid"' in base
