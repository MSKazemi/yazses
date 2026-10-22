"""The flaky-test, rerun and quarantine policy, as checkable rules (#538, CI_POLICY.md §9).

This is the pure half: standard library only, no pytest, no YAML parser, no I/O beyond what a
caller hands in. `tests/quarantine_plugin.py` is the pytest half that applies a quarantine at
run time; `tests/test_flake_policy.py` runs both against the real tree.

Two rules live here.

**A quarantine is a dated, owned, registered exception.** A test may be marked

    @pytest.mark.quarantine(issue=123, owner="MSKazemi", reason="...", expires="2026-12-01")

only if the same test has an entry in `tests/quarantine.toml` with the same four values, the
expiry has not passed, and the expiry is at most `MAX_QUARANTINE_DAYS` away. Anything else is a
problem the guard test reports, and the plugin refuses to honour: an expired or unregistered
quarantine runs as an ordinary blocking test. That is the point -- a temporary exception cannot
quietly become a permanent gap, because on its expiry date it stops being an exception.

**Every `continue-on-error` says when it ends.** A workflow key that lets a job or step fail
must carry, on the same line or in the comment block directly above it, a comment of the form
`# PROMOTE WHEN: <condition>` or `# REMOVE WHEN: <condition>`. A literal `false` needs none.
The scan is line-based on purpose: comments do not survive a YAML parse. The guard test
cross-checks the count against a real parse so a key spelled in a form this scanner cannot see
fails instead of passing unnoticed.
"""

from __future__ import annotations

import ast
import datetime as dt
import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

MARKER = "quarantine"
REQUIRED_FIELDS = ("issue", "owner", "reason", "expires")
REGISTRY_RELPATH = "tests/quarantine.toml"

#: The longest a quarantine may run before someone has to look at it again. Renewal is allowed
#: -- move the date and say why in the linked issue -- but it is an explicit act, reviewed in a
#: diff, never the default.
MAX_QUARANTINE_DAYS = 90

_PROMOTION_COMMENT = re.compile(r"#\s*(PROMOTE|REMOVE) WHEN:\s*\S", re.IGNORECASE)
_COE_KEY = re.compile(r"^(?P<indent>\s*)(?:-\s+)?continue-on-error\s*:\s*(?P<value>[^#]*?)\s*(?:#.*)?$")
#: The `[...]` parameter id pytest appends to the last name of a node id. Test file paths and
#: names never contain `[`, so the first one starts the id.
_PARAM_SUFFIX = re.compile(r"\[.*\]$", re.DOTALL)


# --------------------------------------------------------------------------- quarantine


@dataclass(frozen=True)
class Quarantine:
    """One valid quarantine: what it covers and the four facts that justify it."""

    test: str
    issue: int
    owner: str
    reason: str
    expires: dt.date


@dataclass(frozen=True)
class MarkerUse:
    """A `pytest.mark.quarantine` found in a test file's source.

    `test` is the registry key it applies to (`path::[Class::]function`, no parameter id), or
    empty when the marker sits somewhere this policy does not support. `problems` holds what
    was wrong before any registry lookup (placement, positional arguments, non-literal values).
    """

    test: str
    location: str
    fields: Mapping[str, object]
    problems: tuple[str, ...] = ()


@dataclass
class Registry:
    entries: dict[str, Mapping[str, object]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def _as_date(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return None  # a timestamp is not a review date; be exact
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def validate_fields(
    fields: Mapping[str, object], *, test: str, today: dt.date
) -> tuple[Quarantine | None, list[str]]:
    """Check the four quarantine facts. Returns the quarantine, or None and every problem."""
    problems: list[str] = []
    unknown = sorted(set(fields) - set(REQUIRED_FIELDS) - {"test"})
    if unknown:
        problems.append(f"{test}: unknown quarantine field(s) {unknown}")
    for name in REQUIRED_FIELDS:
        if name not in fields or fields[name] in (None, ""):
            problems.append(f"{test}: quarantine has no {name}")

    issue = fields.get("issue")
    if "issue" in fields and (
        isinstance(issue, bool) or not isinstance(issue, int) or issue <= 0
    ):
        problems.append(f"{test}: issue must be a positive GitHub issue number, got {issue!r}")
    for name in ("owner", "reason"):
        value = fields.get(name)
        if name in fields and value not in (None, "") and (
            not isinstance(value, str) or not value.strip()
        ):
            problems.append(f"{test}: {name} must be non-empty text, got {value!r}")

    expires = None
    if fields.get("expires") not in (None, ""):
        expires = _as_date(fields["expires"])
        if expires is None:
            problems.append(
                f"{test}: expires must be an ISO date (YYYY-MM-DD), got {fields['expires']!r}"
            )
        elif expires < today:
            problems.append(
                f"{test}: quarantine EXPIRED on {expires.isoformat()} (today is "
                f"{today.isoformat()}). Fix the test, or renew the date with a reason in "
                f"issue #{issue}; until then it runs as a blocking test."
            )
        elif (expires - today).days > MAX_QUARANTINE_DAYS:
            problems.append(
                f"{test}: expires {expires.isoformat()} is more than {MAX_QUARANTINE_DAYS} "
                f"days away; a quarantine is reviewed at least that often"
            )

    if problems:
        return None, problems
    assert isinstance(issue, int) and expires is not None
    return (
        Quarantine(
            test=test,
            issue=issue,
            owner=str(fields["owner"]).strip(),
            reason=str(fields["reason"]).strip(),
            expires=expires,
        ),
        [],
    )


def parse_registry(text: str) -> Registry:
    """Parse `tests/quarantine.toml`. Unreadable input is a problem, never an empty registry."""
    registry = Registry()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        registry.problems.append(f"{REGISTRY_RELPATH} is not valid TOML: {exc}")
        return registry
    extra = sorted(set(data) - {MARKER})
    if extra:
        registry.problems.append(f"{REGISTRY_RELPATH}: unknown top-level key(s) {extra}")
    rows = data.get(MARKER, [])
    if not isinstance(rows, list):
        registry.problems.append(f"{REGISTRY_RELPATH}: `{MARKER}` must be an array of tables")
        return registry
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("test"), str) or not row["test"]:
            registry.problems.append(f"{REGISTRY_RELPATH}: entry {index} has no `test`")
            continue
        test = row["test"]
        if test in registry.entries:
            registry.problems.append(f"{REGISTRY_RELPATH}: {test} is listed twice")
            continue
        registry.entries[test] = row
    return registry


def registry_keys_for(nodeid: str) -> list[str]:
    """Registry keys that could cover a collected item, closest first.

    `tests/a.py::TestX::test_y[case-1]` may be covered by `tests/a.py::TestX::test_y` (every
    parameter) or by `tests/a.py::TestX` (a class-level marker). The module alone is never a
    key: a quarantine names what it covers.
    """
    # Strip the parameter id before splitting: an id may itself contain "::".
    parts = _PARAM_SUFFIX.sub("", nodeid).split("::")
    if len(parts) < 2:
        return []
    return ["::".join(parts[:end]) for end in range(len(parts), 1, -1)]


def _same(marker_value: object, registry_value: object) -> bool:
    a, b = _as_date(marker_value), _as_date(registry_value)
    if a is not None or b is not None:
        return a == b
    if isinstance(marker_value, str) and isinstance(registry_value, str):
        return marker_value.strip() == registry_value.strip()
    return marker_value == registry_value


def against_entry(
    fields: Mapping[str, object], key: str, entry: Mapping[str, object], *, today: dt.date
) -> tuple[Quarantine | None, list[str]]:
    """Validate a marker's fields and check they agree with its registry entry."""
    quarantine, problems = validate_fields(fields, test=key, today=today)
    for name in REQUIRED_FIELDS:
        if name in fields and name in entry and not _same(fields[name], entry[name]):
            problems.append(
                f"{key}: marker and {REGISTRY_RELPATH} disagree on {name} "
                f"({fields[name]!r} vs {entry[name]!r})"
            )
    if problems:
        return None, problems
    return quarantine, []


def resolve(
    fields: Mapping[str, object], nodeid: str, registry: Registry, *, today: dt.date
) -> tuple[Quarantine | None, list[str]]:
    """Decide whether a collected item's quarantine marker is honoured.

    Honoured means: the marker's fields are valid, a registry entry covers the item, and the
    two agree on every field. Otherwise the problems say why and the test stays blocking.
    """
    keys = registry_keys_for(nodeid)
    key = next((k for k in keys if k in registry.entries), None)
    if key is None:
        label = keys[0] if keys else nodeid
        _, problems = validate_fields(fields, test=label, today=today)
        problems.append(
            f"{label}: quarantine is not registered in {REGISTRY_RELPATH} (add an entry with "
            f"test = {label!r} and the same issue, owner, reason and expires)"
        )
        return None, problems
    return against_entry(fields, key, registry.entries[key], today=today)


def _mark_attr(node: ast.AST) -> bool:
    """True for `pytest.mark.quarantine` and `mark.quarantine`."""
    if not isinstance(node, ast.Attribute) or node.attr != MARKER:
        return False
    owner = node.value
    return (isinstance(owner, ast.Attribute) and owner.attr == "mark") or (
        isinstance(owner, ast.Name) and owner.id == "mark"
    )


def _marker_fields(call: ast.AST) -> tuple[dict[str, object], list[str]]:
    if not isinstance(call, ast.Call):
        return {}, ["a bare marker carries no issue, owner, reason or expiry"]
    problems = []
    if call.args:
        problems.append("pass issue=, owner=, reason=, expires= as keywords")
    fields: dict[str, object] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            problems.append("**kwargs hides the fields from review; write them out")
            continue
        try:
            fields[keyword.arg] = ast.literal_eval(keyword.value)
        except ValueError:
            problems.append(f"{keyword.arg}= must be a literal so it can be checked")
    return fields, problems


def scan_source(relpath: str, source: str) -> list[MarkerUse]:
    """Find every quarantine marker in one test file's source."""
    if MARKER not in source:
        # `mark.quarantine` is spelt out wherever it is used, so a file that never says
        # `quarantine` has none. The policy test calls this for every test file, and
        # parsing all of them was nearly all of its runtime. A file that does not parse
        # still fails, at collection.
        return []
    tree = ast.parse(source, filename=relpath)
    uses: list[MarkerUse] = []
    consumed: set[int] = set()

    def visit(body: Iterable[ast.stmt], prefix: str) -> None:
        for node in body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            key = f"{prefix}::{node.name}"
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if _mark_attr(target):
                    consumed.add(id(target))
                    fields, problems = _marker_fields(decorator)
                    uses.append(
                        MarkerUse(
                            test=key,
                            location=f"{relpath}:{decorator.lineno}",
                            fields=fields,
                            problems=tuple(f"{key}: {p}" for p in problems),
                        )
                    )
            if isinstance(node, ast.ClassDef):
                visit(node.body, key)

    visit(tree.body, relpath)
    for node in ast.walk(tree):
        if _mark_attr(node) and id(node) not in consumed:
            location = f"{relpath}:{getattr(node, 'lineno', 0)}"
            uses.append(
                MarkerUse(
                    test="",
                    location=location,
                    fields={},
                    problems=(
                        f"{location}: a quarantine marker is only supported as a decorator on a "
                        f"test function or class (not pytestmark, pytest.param or add_marker), "
                        f"so the registry can name exactly what it covers",
                    ),
                )
            )
    return uses


def check(uses: Iterable[MarkerUse], registry: Registry, *, today: dt.date) -> list[str]:
    """Every problem with the suite's quarantines. Empty means the policy holds."""
    problems = list(registry.problems)
    marked: set[str] = set()
    for use in uses:
        problems.extend(use.problems)
        if not use.test:
            continue
        marked.add(use.test)
        if use.test not in registry.entries:
            _, field_problems = validate_fields(use.fields, test=use.test, today=today)
            problems.extend(field_problems)
            problems.append(
                f"{use.test} ({use.location}): quarantine is not registered in "
                f"{REGISTRY_RELPATH}"
            )
            continue
        _, entry_problems = against_entry(
            use.fields, use.test, registry.entries[use.test], today=today
        )
        problems.extend(entry_problems)
    for test, entry in registry.entries.items():
        if test not in marked:
            # A marked entry was already checked through its marker, which must agree with it.
            _, entry_problems = validate_fields(entry, test=test, today=today)
            problems.extend(f"{REGISTRY_RELPATH}: {p}" for p in entry_problems)
            problems.append(
                f"{REGISTRY_RELPATH}: {test} has no quarantine marker in the source. If the "
                f"quarantine is over, delete the entry; if the test moved, update `test`."
            )
    return list(dict.fromkeys(problems))


def summary_lines(records: Iterable[tuple[str, str, Quarantine | None, list[str]]]) -> list[str]:
    """Plain-text lines for the terminal section listing quarantined tests and their results.

    Each record is (nodeid, outcome, honoured quarantine or None, problems).
    """
    lines = []
    for nodeid, outcome, quarantine, problems in records:
        if quarantine is not None:
            lines.append(
                f"{outcome.upper():<8} {nodeid}  #{quarantine.issue} owner={quarantine.owner} "
                f"expires={quarantine.expires.isoformat()}: {quarantine.reason}"
            )
        else:
            lines.append(f"{outcome.upper():<8} {nodeid}  NOT HONOURED, ran as blocking:")
            lines.extend(f"         - {p}" for p in problems)
    return lines


def summary_markdown(records: Iterable[tuple[str, str, Quarantine | None, list[str]]]) -> str:
    """The same records as a GitHub step-summary table, so CI shows them on the run page."""
    rows = [
        "### Quarantined tests (CI_POLICY.md §9)",
        "",
        "| Result | Test | Issue | Owner | Expires | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for nodeid, outcome, quarantine, problems in records:
        cell = nodeid.replace("|", "\\|")
        if quarantine is not None:
            reason = quarantine.reason.replace("|", "\\|")
            rows.append(
                f"| {outcome} | `{cell}` | #{quarantine.issue} | {quarantine.owner} | "
                f"{quarantine.expires.isoformat()} | {reason} |"
            )
        else:
            why = "; ".join(problems).replace("|", "\\|")
            rows.append(f"| {outcome} (NOT honoured) | `{cell}` | | | | {why} |")
    return "\n".join(rows) + "\n"


# --------------------------------------------------------------------------- continue-on-error


@dataclass(frozen=True)
class ContinueOnError:
    line: int
    value: str
    has_condition: bool


def find_continue_on_error(text: str) -> list[ContinueOnError]:
    """Every block-style `continue-on-error:` key in a workflow, with whether it says when it ends.

    "Says when it ends" means a `# PROMOTE WHEN:` / `# REMOVE WHEN:` comment on the same line,
    or in the unbroken run of comment lines directly above it. A blank line or another key in
    between breaks adjacency -- the condition has to be next to the switch it governs.
    """
    lines = text.splitlines()
    found = []
    for index, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        match = _COE_KEY.match(line)
        if not match:
            continue
        value = match.group("value").strip().strip("'\"")
        has = bool(_PROMOTION_COMMENT.search(line))
        above = index - 1
        while not has and above >= 0 and lines[above].lstrip().startswith("#"):
            has = bool(_PROMOTION_COMMENT.search(lines[above]))
            above -= 1
        found.append(ContinueOnError(line=index + 1, value=value, has_condition=has))
    return found


def continue_on_error_problems(relpath: str, text: str) -> list[str]:
    """Each `continue-on-error` that may be true and does not state its promotion condition."""
    return [
        f"{relpath}:{key.line}: `continue-on-error: {key.value}` has no adjacent "
        f"`# PROMOTE WHEN: ...` or `# REMOVE WHEN: ...` comment (CI_POLICY.md §9.4)"
        for key in find_continue_on_error(text)
        if key.value.lower() != "false" and not key.has_condition
    ]
