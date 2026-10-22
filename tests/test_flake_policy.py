"""The flaky-test / rerun / quarantine policy is enforced, not just written down (#538).

`.github/CI_POLICY.md` §9 says a quarantine needs a linked issue, an owner, a reason and an
expiry, that quarantined coverage stays visible, and that every `continue-on-error` states when
it ends. Each of those is a rule a well-meaning contributor breaks by accident, and none of them
turns anything red on its own: an expired quarantine keeps hiding a failure, an unexplained
`continue-on-error` keeps a job advisory forever. This file makes each one loud.

Three groups:

- **the rules** (`tests/flake_policy.py`), exercised case by case, including the ways a check
  can pass by not looking -- unreadable TOML, an empty scan, a key the line scanner misses;
- **the tree**: every quarantine marker in `tests/` and every `continue-on-error` in
  `.github/workflows/` checked against them;
- **the plugin** (`tests/quarantine_plugin.py`), run in a child pytest so its effect on real
  outcomes and exit codes is observed rather than assumed.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from tests import flake_policy as fp

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
TODAY = dt.date(2026, 10, 21)

GOOD = {"issue": 538, "owner": "MSKazemi", "reason": "times out 1 in 40", "expires": "2026-11-01"}


def _registry(**entries: dict) -> fp.Registry:
    lines = []
    for test, fields in entries.items():
        lines.append("[[quarantine]]")
        lines.append(f"test = {test!r}")
        for name, value in fields.items():
            lines.append(f"{name} = {value!r}" if isinstance(value, str) else f"{name} = {value}")
    return fp.parse_registry("\n".join(lines))


def _uses(source: str, relpath: str = "tests/test_x.py") -> list[fp.MarkerUse]:
    return fp.scan_source(relpath, textwrap.dedent(source))


def _decorated(fields: str) -> str:
    return f"""
        import pytest

        @pytest.mark.quarantine({fields})
        def test_y():
            pass
    """


GOOD_ARGS = 'issue=538, owner="MSKazemi", reason="times out 1 in 40", expires="2026-11-01"'


# --------------------------------------------------------------------------- the rules


def test_a_complete_registered_quarantine_is_honoured():
    registry = _registry(**{"tests/test_x.py::test_y": GOOD})
    assert fp.check(_uses(_decorated(GOOD_ARGS)), registry, today=TODAY) == []
    quarantine, problems = fp.resolve(GOOD, "tests/test_x.py::test_y[a-1]", registry, today=TODAY)
    assert problems == []
    assert quarantine is not None and quarantine.issue == 538
    assert quarantine.expires == dt.date(2026, 11, 1)


@pytest.mark.parametrize(
    "drop", ["issue", "owner", "reason", "expires"], ids=lambda name: f"no-{name}"
)
def test_a_quarantine_missing_any_field_is_refused(drop):
    fields = {k: v for k, v in GOOD.items() if k != drop}
    args = ", ".join(f"{k}={v!r}" for k, v in fields.items())
    registry = _registry(**{"tests/test_x.py::test_y": fields})
    problems = fp.check(_uses(_decorated(args)), registry, today=TODAY)
    assert any(f"has no {drop}" in p for p in problems), problems
    _, runtime = fp.resolve(fields, "tests/test_x.py::test_y", registry, today=TODAY)
    assert runtime, "the plugin must not honour what the guard refuses"


def test_an_expired_quarantine_is_refused_and_says_it_runs_blocking():
    stale = dict(GOOD, expires="2026-10-20")
    registry = _registry(**{"tests/test_x.py::test_y": stale})
    args = GOOD_ARGS.replace("2026-11-01", "2026-10-20")
    problems = fp.check(_uses(_decorated(args)), registry, today=TODAY)
    assert any("EXPIRED on 2026-10-20" in p and "blocking" in p for p in problems), problems
    quarantine, _ = fp.resolve(stale, "tests/test_x.py::test_y", registry, today=TODAY)
    assert quarantine is None


def test_the_expiry_day_itself_is_still_inside_the_quarantine():
    fields = dict(GOOD, expires=TODAY.isoformat())
    registry = _registry(**{"tests/test_x.py::test_y": fields})
    assert fp.resolve(fields, "tests/test_x.py::test_y", registry, today=TODAY)[1] == []


def test_a_quarantine_cannot_be_dated_into_the_far_future():
    far = (TODAY + dt.timedelta(days=fp.MAX_QUARANTINE_DAYS + 1)).isoformat()
    fields = dict(GOOD, expires=far)
    registry = _registry(**{"tests/test_x.py::test_y": fields})
    _, problems = fp.resolve(fields, "tests/test_x.py::test_y", registry, today=TODAY)
    assert any("more than 90 days away" in p for p in problems), problems
    edge = dict(GOOD, expires=(TODAY + dt.timedelta(days=fp.MAX_QUARANTINE_DAYS)).isoformat())
    registry = _registry(**{"tests/test_x.py::test_y": edge})
    assert fp.resolve(edge, "tests/test_x.py::test_y", registry, today=TODAY)[1] == []


@pytest.mark.parametrize(
    ("name", "value", "needle"),
    [
        ("issue", 0, "positive GitHub issue number"),
        ("issue", "538", "positive GitHub issue number"),
        ("issue", True, "positive GitHub issue number"),
        ("owner", "   ", "non-empty text"),
        ("expires", "next month", "ISO date"),
    ],
    ids=["issue-zero", "issue-string", "issue-bool", "owner-blank", "expires-prose"],
)
def test_malformed_fields_are_refused(name, value, needle):
    _, problems = fp.validate_fields(dict(GOOD, **{name: value}), test="t", today=TODAY)
    assert any(needle in p for p in problems), problems


def test_an_unregistered_marker_is_refused():
    problems = fp.check(_uses(_decorated(GOOD_ARGS)), fp.Registry(), today=TODAY)
    assert any("not registered" in p for p in problems), problems
    _, runtime = fp.resolve(GOOD, "tests/test_x.py::test_y", fp.Registry(), today=TODAY)
    assert any("not registered" in p for p in runtime), runtime


def test_a_registry_entry_whose_marker_is_gone_is_refused():
    registry = _registry(**{"tests/test_x.py::test_gone": GOOD})
    problems = fp.check([], registry, today=TODAY)
    assert any("test_gone has no quarantine marker" in p for p in problems), problems


def test_marker_and_registry_must_agree():
    registry = _registry(**{"tests/test_x.py::test_y": dict(GOOD, owner="someone-else")})
    problems = fp.check(_uses(_decorated(GOOD_ARGS)), registry, today=TODAY)
    assert any("disagree on owner" in p for p in problems), problems


def test_a_class_marker_covers_its_methods():
    source = f"""
        import pytest

        @pytest.mark.quarantine({GOOD_ARGS})
        class TestSocket:
            def test_a(self):
                pass
    """
    uses = _uses(source)
    assert [u.test for u in uses] == ["tests/test_x.py::TestSocket"]
    registry = _registry(**{"tests/test_x.py::TestSocket": GOOD})
    assert fp.check(uses, registry, today=TODAY) == []
    nodeid = "tests/test_x.py::TestSocket::test_a[p0]"
    assert fp.resolve(GOOD, nodeid, registry, today=TODAY)[1] == []


def test_registry_keys_strip_parameters_and_never_widen_to_the_module():
    assert fp.registry_keys_for("tests/a.py::TestX::test_y[x::y-1]") == [
        "tests/a.py::TestX::test_y",
        "tests/a.py::TestX",
    ]
    assert fp.registry_keys_for("tests/a.py") == []


@pytest.mark.parametrize(
    ("source", "needle"),
    [
        (_decorated(""), "has no issue"),
        (
            """
            import pytest

            @pytest.mark.quarantine
            def test_y():
                pass
            """,
            "bare marker",
        ),
        (_decorated('538, owner="o", reason="r", expires="2026-11-01"'), "as keywords"),
        (_decorated(GOOD_ARGS.replace('"MSKazemi"', "OWNER")), "must be a literal"),
        (_decorated("**FIELDS"), "write them out"),
        (
            f"""
            import pytest

            pytestmark = pytest.mark.quarantine({GOOD_ARGS})
            """,
            "only supported as a decorator",
        ),
        (
            f"""
            import pytest

            @pytest.mark.parametrize("v", [pytest.param(1, marks=pytest.mark.quarantine({GOOD_ARGS}))])
            def test_y(v):
                pass
            """,
            "only supported as a decorator",
        ),
    ],
    ids=["empty", "bare", "positional", "non-literal", "star-kwargs", "pytestmark", "param"],
)
def test_markers_the_registry_cannot_name_exactly_are_refused(source, needle):
    registry = _registry(**{"tests/test_x.py::test_y": GOOD})
    problems = fp.check(_uses(source), registry, today=TODAY)
    assert any(needle in p for p in problems), problems


def test_an_unreadable_registry_is_a_problem_not_an_empty_registry():
    registry = fp.parse_registry("[[quarantine]\ntest = ")
    assert registry.problems and "not valid TOML" in registry.problems[0]
    assert fp.check([], registry, today=TODAY), "a broken registry must fail the guard"


def test_registry_shape_errors_are_reported():
    assert any("unknown top-level" in p for p in fp.parse_registry("exemptions = []").problems)
    assert any("has no `test`" in p for p in fp.parse_registry("[[quarantine]]\nissue = 1").problems)
    twice = '[[quarantine]]\ntest = "tests/a.py::t"\n[[quarantine]]\ntest = "tests/a.py::t"\n'
    assert any("listed twice" in p for p in fp.parse_registry(twice).problems)


def test_a_toml_date_and_an_iso_string_are_the_same_expiry():
    registry = fp.parse_registry(
        '[[quarantine]]\ntest = "tests/test_x.py::test_y"\nissue = 538\nowner = "MSKazemi"\n'
        'reason = "times out 1 in 40"\nexpires = 2026-11-01\n'
    )
    assert fp.check(_uses(_decorated(GOOD_ARGS)), registry, today=TODAY) == []


def test_the_summary_names_every_quarantine_and_every_refusal():
    quarantine = fp.Quarantine("t", 538, "MSKazemi", "flaky | socket", dt.date(2026, 11, 1))
    records = [
        ("tests/a.py::t", "failed", quarantine, []),
        ("tests/a.py::u", "failed", None, ["tests/a.py::u: quarantine EXPIRED on 2026-10-01"]),
    ]
    text = "\n".join(fp.summary_lines(records))
    assert "FAILED   tests/a.py::t  #538 owner=MSKazemi expires=2026-11-01" in text
    assert "NOT HONOURED, ran as blocking" in text and "EXPIRED" in text
    markdown = fp.summary_markdown(records)
    assert "| failed | `tests/a.py::t` | #538 | MSKazemi | 2026-11-01 | flaky \\| socket |" in markdown
    assert "failed (NOT honoured)" in markdown


# continue-on-error ---------------------------------------------------------------------


def _coe(text: str) -> list[str]:
    return fp.continue_on_error_problems("wf.yml", textwrap.dedent(text))


def test_a_continue_on_error_without_a_condition_is_reported():
    problems = _coe(
        """
        jobs:
          a:
            # advisory because it is new
            continue-on-error: true
        """
    )
    assert problems == [
        "wf.yml:5: `continue-on-error: true` has no adjacent `# PROMOTE WHEN: ...` or "
        "`# REMOVE WHEN: ...` comment (CI_POLICY.md §9.4)"
    ]


@pytest.mark.parametrize(
    "text",
    [
        """
        a:
          # Advisory: never run here.
          # PROMOTE WHEN: green on three consecutive pushes to main.
          continue-on-error: true
        """,
        """
        a:
          # REMOVE WHEN: the artefact quota is raised.
          # (convenience copy only)
          continue-on-error: true
        """,
        """
        a:
          continue-on-error: true  # promote when: it has passed once
        """,
        """
        steps:
          # PROMOTE WHEN: never -- best-effort by design; REMOVE WHEN the fork is retired.
          - continue-on-error: true
        """,
        """
        a:
          continue-on-error: false
        """,
    ],
    ids=["above", "above-not-last", "trailing", "list-item", "literal-false"],
)
def test_a_stated_condition_or_a_literal_false_passes(text):
    assert _coe(text) == []


@pytest.mark.parametrize(
    "text",
    [
        """
        a:
          # PROMOTE WHEN: it has passed once.

          continue-on-error: true
        """,
        """
        a:
          # PROMOTE WHEN: it has passed once.
          runs-on: ubuntu-latest
          continue-on-error: true
        """,
        """
        a:
          # PROMOTE WHEN:
          continue-on-error: true
        """,
        """
        a:
          continue-on-error: ${{ matrix.experimental }}
        """,
    ],
    ids=["blank-line-between", "key-between", "empty-condition", "expression"],
)
def test_a_condition_that_is_not_adjacent_or_not_stated_does_not_count(text):
    assert len(_coe(text)) == 1


def test_a_comment_mentioning_continue_on_error_is_not_a_key():
    assert fp.find_continue_on_error("a:\n  # continue-on-error: true would hide it\n") == []


# --------------------------------------------------------------------------- the tree


def _test_sources() -> list[Path]:
    return sorted(p for p in (ROOT / "tests").rglob("*.py") if "fixtures" not in p.parts)


def test_the_registry_in_the_tree_is_readable():
    path = ROOT / fp.REGISTRY_RELPATH
    assert path.is_file(), f"{fp.REGISTRY_RELPATH} is the quarantine registry; keep it"
    assert fp.parse_registry(path.read_text(encoding="utf-8")).problems == []


def test_every_quarantine_in_the_suite_is_registered_owned_and_unexpired():
    sources = _test_sources()
    assert len(sources) > 100, "the scan found almost no test files; it is looking elsewhere"
    uses = []
    for path in sources:
        relpath = path.relative_to(ROOT).as_posix()
        uses += fp.scan_source(relpath, path.read_text(encoding="utf-8"))
    registry = fp.parse_registry((ROOT / fp.REGISTRY_RELPATH).read_text(encoding="utf-8"))
    problems = fp.check(uses, registry, today=dt.date.today())
    assert problems == [], "quarantine policy (CI_POLICY.md §9.3):\n" + "\n".join(problems)


def _workflows() -> list[Path]:
    files = sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])
    assert files, "no workflows found; the guard would pass by looking at nothing"
    return files


def test_every_continue_on_error_states_its_promotion_or_removal_condition():
    problems = []
    for path in _workflows():
        problems += fp.continue_on_error_problems(
            path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8")
        )
    assert problems == [], (
        "every continue-on-error needs an adjacent `# PROMOTE WHEN: <condition>` or "
        "`# REMOVE WHEN: <condition>` comment (CI_POLICY.md §9.4):\n" + "\n".join(problems)
    )


def _yaml_keys(node: object) -> int:
    if isinstance(node, dict):
        return sum(
            (key == "continue-on-error") + _yaml_keys(value) for key, value in node.items()
        )
    if isinstance(node, list):
        return sum(_yaml_keys(value) for value in node)
    return 0


def test_the_line_scanner_sees_every_key_a_yaml_parser_sees():
    """A flow-style `{continue-on-error: true}` would slip past the line scan; this catches it."""
    total = 0
    for path in _workflows():
        text = path.read_text(encoding="utf-8")
        parsed = _yaml_keys(yaml.safe_load(text))
        scanned = len(fp.find_continue_on_error(text))
        assert scanned == parsed, (
            f"{path.name}: YAML has {parsed} continue-on-error key(s), the line scanner found "
            f"{scanned}. Write the key in block style so its comment can be checked."
        )
        total += parsed
    assert total > 0, "no continue-on-error anywhere: the comparison above proved nothing"


# --------------------------------------------------------------------------- the plugin


def _run_child(tmp_path: Path, test_source: str, registry: str) -> tuple[int, str, str]:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "quarantine.toml").write_text(registry, encoding="utf-8")
    (tmp_path / "tests" / "test_child.py").write_text(
        textwrap.dedent(test_source), encoding="utf-8"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    step_summary = tmp_path / "step-summary.md"
    # PYTHONIOENCODING: the child prints "§" (CI_POLICY.md §9.3). On Windows a piped
    # child writes cp1252 by default, which the utf-8 read below cannot decode, so
    # stdout came back None and three tests failed on windows-latest only.
    env = dict(os.environ, PYTHONPATH=str(ROOT), GITHUB_STEP_SUMMARY=str(step_summary),
               PYTHONIOENCODING="utf-8")
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-p", "tests.quarantine_plugin",
            "-p", "no:cacheprovider", "-rx", "-v", "-c", str(tmp_path / "pytest.ini"),
            str(tmp_path / "tests" / "test_child.py"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    summary = step_summary.read_text(encoding="utf-8") if step_summary.exists() else ""
    return result.returncode, result.stdout + result.stderr, summary


def _child_registry(expires: dt.date, *tests: str) -> str:
    return "".join(
        f'[[quarantine]]\ntest = "tests/test_child.py::{name}"\nissue = 538\n'
        f'owner = "MSKazemi"\nreason = "child run"\nexpires = {expires.isoformat()}\n'
        for name in tests
    )


def _child_source(expires: dt.date) -> str:
    args = f'issue=538, owner="MSKazemi", reason="child run", expires="{expires.isoformat()}"'
    return f"""
        import pytest

        @pytest.mark.quarantine({args})
        def test_flaky_fails():
            assert False, "the flake"

        @pytest.mark.quarantine({args})
        def test_flaky_passes():
            pass

        def test_ordinary():
            pass
    """


def test_an_honoured_quarantine_still_runs_does_not_block_and_is_listed(tmp_path):
    soon = dt.date.today() + dt.timedelta(days=10)
    code, out, summary = _run_child(
        tmp_path,
        _child_source(soon),
        _child_registry(soon, "test_flaky_fails", "test_flaky_passes"),
    )
    assert code == 0, out
    assert "test_child.py::test_flaky_fails XFAIL" in out, out
    assert "quarantined: #538, owner MSKazemi" in out, out
    assert "test_child.py::test_flaky_passes PASSED" in out, out
    assert "quarantined tests (2;" in out, out
    assert "FAILED   tests/test_child.py::test_flaky_fails  #538 owner=MSKazemi" in out, out
    assert "PASSED   tests/test_child.py::test_flaky_passes  #538" in out, out
    assert "| failed | `tests/test_child.py::test_flaky_fails` | #538 |" in summary, summary


def test_an_expired_quarantine_runs_as_a_blocking_test(tmp_path):
    past = dt.date.today() - dt.timedelta(days=1)
    code, out, summary = _run_child(
        tmp_path,
        _child_source(past),
        _child_registry(past, "test_flaky_fails", "test_flaky_passes"),
    )
    assert code == 1, out
    assert "test_child.py::test_flaky_fails FAILED" in out, out
    assert "NOT HONOURED, ran as blocking" in out and "EXPIRED" in out, out
    assert "failed (NOT honoured)" in summary, summary


def test_an_unregistered_quarantine_runs_as_a_blocking_test(tmp_path):
    soon = dt.date.today() + dt.timedelta(days=10)
    code, out, _ = _run_child(tmp_path, _child_source(soon), "")
    assert code == 1, out
    assert "test_child.py::test_flaky_fails FAILED" in out, out
    assert "not registered" in out, out


def test_a_run_without_quarantines_prints_no_section(tmp_path):
    code, out, summary = _run_child(tmp_path, "def test_plain():\n    pass\n", "")
    assert code == 0, out
    assert "quarantined tests" not in out and summary == ""
