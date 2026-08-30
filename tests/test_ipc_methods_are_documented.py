"""The IPC table in `design/architecture.md` must describe the daemon that exists.

`design/architecture.md` is the reference a contributor reads before touching the
daemon, and `hooks/design_tier.py` publishes it to the documentation site, so it is a
reader-facing surface rather than a private note. Its IPC table listed **nine** of the
daemon's **twenty-one** registered methods -- everything added since the v0.3 line
(meeting capture, staged mode, punch-in, read-back, recall, scratch, the two tray mic
actions, the learning signal, the MCP question) was simply absent -- and three of the
nine it did list were annotated `CLI -> daemon` when no CLI path had ever sent them:
`remote_status`, `streaming_enable` and `streaming_disable` appear nowhere in `src/`
outside their own registration.

The second half is the one worth a test. An absent row is a gap a reader can notice;
a row that names a caller which does not exist is a claim, and it reads as "the CLI can
toggle streaming at runtime" -- a capability the product does not have. Nothing checked
either half, because the table was prose.

Both columns are therefore derived here rather than restated: the method set comes from
`server.register(...)` in `core/daemon.py`, and reachability from the call sites in
`src/`. Wiring one of the three up, or dropping a caller, fails this file until the
table says so.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURE = ROOT / "design/architecture.md"
DAEMON = ROOT / "src/yazses/core/daemon.py"
SRC = ROOT / "src/yazses"

#: The cell used for a method nothing sends. Checked in both directions, so it cannot
#: quietly stay behind once someone wires one of them to a command.
UNREACHED = "nothing"


def _registered() -> list[str]:
    """Method names the daemon registers, in registration order."""
    names = re.findall(r'server\.register\(\s*"([a-z_]+)"', DAEMON.read_text(encoding="utf-8"))
    # A regex that stopped matching would otherwise make every assertion below vacuous:
    # an empty "registered" set equals an empty "documented" set.
    assert len(names) >= 10, (
        f"only {len(names)} `server.register(...)` calls were found in {DAEMON.name} -- "
        "the pattern this test derives the method list from has stopped matching, so it "
        "is checking nothing."
    )
    return names


def _table_rows() -> list[tuple[str, str]]:
    """`(method, reached-from)` for every row of the `## IPC methods` table.

    Anchored on the exact heading *line*: the file also contains
    `### IPC methods (v1.0 additions)`, which contains `## IPC methods` as a substring,
    and a substring search lands on the historical section instead of this one.
    """
    lines = ARCHITECTURE.read_text(encoding="utf-8").splitlines()
    heads = [i for i, ln in enumerate(lines) if ln.strip() == "## IPC methods"]
    assert len(heads) == 1, (
        f"expected exactly one `## IPC methods` heading in {ARCHITECTURE.name}, found "
        f"{len(heads)} -- this test cannot tell which table it is checking."
    )
    rows: list[tuple[str, str]] = []
    for line in lines[heads[0] + 1:]:
        if line.strip() == "---":
            break
        if not line.startswith("|"):
            continue
        # `\|` inside a cell is an escaped pipe (`mean(\|samples\|)`), not a separator.
        cells = [c.strip() for c in line.replace(r"\|", "\0").strip("|").split("|")]
        method = cells[0].strip("`")
        if not re.fullmatch(r"[a-z_]+", method):
            continue  # the header row and its `|---|` rule
        rows.append((method, cells[1].replace("\0", "|").strip("*`").strip()))
    assert rows, (
        "no rows were parsed out of the `## IPC methods` table. A table this test cannot "
        "read must fail, not report compliance."
    )
    return rows


def _callers(method: str) -> list[str]:
    """Files under `src/` that send *method* over IPC, excluding the daemon itself.

    Matches the call expression rather than the bare name: `"status"`, `"inject"` and
    `"staged"` all occur in this tree as feature slugs, subprocess arguments and
    dictionary keys, and counting those would make an unreachable method look wired.
    A comment is allowed between the parenthesis and the name because one real call
    site (`overlay/poller.py`) carries a `# type: ignore` there -- the first version of
    this pattern reported that caller as absent.
    """
    pattern = re.compile(r'(?:\.call|_call|_ipc)\(\s*(?:#[^\n]*\n\s*)*"%s"' % re.escape(method))
    found = []
    for path in sorted(SRC.rglob("*.py")):
        if path == DAEMON:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            found.append(path.relative_to(ROOT).as_posix())
    return found


def test_every_registered_method_is_in_the_table() -> None:
    documented = {m for m, _ in _table_rows()}
    missing = sorted(set(_registered()) - documented)
    assert not missing, (
        f"{len(missing)} IPC method(s) the daemon registers are absent from the table in "
        f"design/architecture.md: {missing}. The table is a reader-facing reference and "
        "is published to the docs site; a method that is not in it does not exist as far "
        "as a contributor is concerned."
    )


def test_the_table_invents_no_method() -> None:
    extra = sorted({m for m, _ in _table_rows()} - set(_registered()))
    assert not extra, (
        f"the table documents {extra}, which the daemon does not register. A row for a "
        "method that cannot be called is worse than no row: it is a documented API that "
        "answers nothing."
    )


def test_the_caller_probe_can_return_a_positive() -> None:
    """Without this, every assertion about reachability below is satisfied by a probe
    that has silently stopped finding anything, and the table's `nothing` cells would
    look correct precisely when they are not."""
    assert _callers("status"), (
        "`status` is polled by the CLI, the tray and the overlay, so a probe that finds "
        "no caller for it is broken, not evidence about the tree."
    )


@pytest.mark.parametrize("row", _table_rows(), ids=lambda r: r[0])
def test_the_reached_from_column_matches_the_tree(row: tuple[str, str]) -> None:
    method, reached = row
    callers = _callers(method)
    if reached == UNREACHED:
        assert not callers, (
            f"`{method}` is documented as reached from {UNREACHED!r}, but {callers} send "
            "it. It has been wired up since the table was written -- say what reaches it, "
            "and drop it from the paragraph about unreachable methods below the table."
        )
    else:
        assert callers, (
            f"the table says `{method}` is reached from {reached!r}, and nothing in src/ "
            f"sends it. That is the defect this file exists for: `remote_status`, "
            "`streaming_enable` and `streaming_disable` were all documented as "
            "`CLI -> daemon` with no CLI path to them. Either wire it up, or set the "
            f"cell to {UNREACHED!r} and explain why it is unreachable."
        )


def test_the_unreachable_methods_are_named_in_prose_too() -> None:
    """A one-word cell is easy to skim past, and the reason a method has no caller is
    what a reader needs. The paragraph under the table carries it; this keeps the two
    from drifting apart."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    unreached = [m for m, r in _table_rows() if r == UNREACHED]
    assert unreached, "the table no longer marks any method unreachable -- if all three "\
        "were wired up, delete this test with the paragraph it guards."
    after = text.split("| `%s` | %s |" % (unreached[-1], UNREACHED))[-1]
    for method in unreached:
        assert f"`{method}`" in after or "registered, implemented, and unreachable" in after, (
            f"`{method}` is marked unreachable in the table but the paragraph under it "
            "does not account for it."
        )
