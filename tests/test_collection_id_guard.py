"""The collection guard that keeps a giant test id from silently breaking CI logs."""

from __future__ import annotations

import subprocess
import sys
import textwrap

from tests.conftest import MAX_TEST_ID_CHARS


def _collect(tmp_path, body: str):
    # A throwaway project with its own conftest-free tree: the guard lives in the repo's
    # conftest, so load it explicitly with -p to test the hook on a controlled file.
    test = tmp_path / "test_ids.py"
    test.write_text(textwrap.dedent(body), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         "-p", "tests.conftest", str(test)],
        capture_output=True, text=True, timeout=120, encoding="utf-8",
    )


def test_a_payload_used_as_its_own_id_fails_collection(tmp_path) -> None:
    out = _collect(
        tmp_path,
        f"""
        import pytest

        @pytest.mark.parametrize("p", [b"[" * {MAX_TEST_ID_CHARS + 10}])
        def test_x(p):
            pass
        """,
    )
    assert out.returncode != 0
    assert "exceed" in (out.stdout + out.stderr)


def test_an_explicit_short_id_collects_normally(tmp_path) -> None:
    out = _collect(
        tmp_path,
        f"""
        import pytest

        @pytest.mark.parametrize("p", [pytest.param(b"[" * {MAX_TEST_ID_CHARS + 10}, id="deep")])
        def test_x(p):
            pass
        """,
    )
    assert out.returncode == 0, out.stdout + out.stderr
