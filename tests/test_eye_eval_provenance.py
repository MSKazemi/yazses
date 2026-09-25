"""What the eye-eval provenance collector reads — and the five things it cannot read.

`design/eye-control/METRICS.md` lists hostname, login username, serial number, MAC address
and full device UUID as "do not collect". The strongest form of that promise is that no
function here reads any of them, so this file asserts the absence directly: it walks the
collector's own source for the stdlib calls that would return one.

The rest is the mapping onto the result envelope, which is pure given its inputs and is
therefore tested against constructed inputs rather than against whatever machine ran the
suite.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from yazses.eyeeval import Provenance, collect_provenance, local_identifiers
from yazses.eyeeval.provenance import (
    _git_commit,
    as_sections,
    fingerprint,
    session_type,
)

SHA = "0123456789abcdef0123456789abcdef01234567"


# --- the absent five --------------------------------------------------------------------


def test_the_collector_never_asks_for_the_node_name() -> None:
    """`platform.uname()` carries the hostname in field 1 and `platform.node()` *is* it.

    One `asdict(platform.uname())` would have put the hostname in every result ever
    produced, which is why the fields are read one at a time. `platform.node()` appears
    exactly once, inside `local_identifiers`, whose whole job is to feed the sweep that
    proves the hostname is *not* in the document.
    """
    source = Path(
        __import__("yazses.eyeeval.provenance", fromlist=["x"]).__file__ or ""
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "platform":
                calls.append(node.func.attr)
    assert "uname" not in calls, "platform.uname() field 1 is the hostname"
    assert calls.count("node") == 1, (
        "platform.node() is the hostname; it belongs only in local_identifiers(), which "
        "exists so the sweep can prove the hostname never reached a result"
    )


def test_the_collected_provenance_carries_no_identifier_of_this_machine() -> None:
    """The real collector on this real machine, checked against this machine's own names."""
    from yazses.eyeeval import privacy_problems

    prov = collect_provenance()
    assert privacy_problems(as_sections(prov), local_identifiers()) == []


def test_local_identifiers_are_read_but_never_returned_as_provenance() -> None:
    """They are inputs to a guard, not fields of a document."""
    ids = local_identifiers()
    sections = as_sections(collect_provenance())
    flat = repr(sections)
    if len(ids.hostname) >= 3:
        assert ids.hostname not in flat
    for home in ids.home_paths:
        assert home not in flat


# --- the mapping onto the envelope ---------------------------------------------------------


def test_every_required_section_key_is_produced() -> None:
    """The collector must fill exactly what the schema demands, or a run fails at the end."""
    from yazses.eyeeval import REQUIRED_SECTIONS

    sections = as_sections(collect_provenance())
    for name in ("machine", "os_session", "display"):
        assert set(REQUIRED_SECTIONS[name]) <= set(sections[name]), name
    # `software` additionally gains `perception_backend` and `generator` from the runner.
    assert {"yazses_version", "git_commit", "python_version"} <= set(sections["software"])


def test_ram_is_absent_rather_than_zero_when_it_cannot_be_read() -> None:
    """A machine with no RAM does not exist, so a 0.0 could only be a failed measurement
    wearing the costume of one (METRICS.md 'Missing data', applied to provenance)."""
    sections = as_sections(Provenance())
    assert sections["machine"]["ram_gb"] is None


def test_the_topology_fingerprint_is_stable_and_geometry_only() -> None:
    a = Provenance(displays=({"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080},))
    b = Provenance(displays=({"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1200},))
    assert as_sections(a)["display"]["topology_fingerprint"] == as_sections(a)["display"]["topology_fingerprint"]
    assert as_sections(a)["display"]["topology_fingerprint"] != as_sections(b)["display"]["topology_fingerprint"]
    assert fingerprint([]).startswith("sha256:")


def test_a_display_entry_carries_no_connector_name() -> None:
    """The X11 reader knows the connector (`eDP-1`); an index tells two monitors apart
    just as well, and a field that is not needed is a field that cannot leak."""
    for entry in as_sections(collect_provenance())["display"]["displays"]:
        assert "identifier" not in entry


# --- session type is a pure mapping ---------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"XDG_SESSION_TYPE": "x11"}, "x11"),
        ({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "GNOME"}, "wayland_gnome"),
        ({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"}, "wayland_kde"),
        ({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "plasmawayland"}, "wayland_kde"),
        ({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "sway"}, "wayland_other"),
        ({"XDG_SESSION_TYPE": "tty"}, "headless"),
        ({}, "headless"),
    ],
)
def test_the_session_type_mapping(env: dict[str, str], expected: str) -> None:
    """"headless" is the honest answer for a CI runner and for an unrecognised session.
    Guessing "x11" there would put a wrong bucket on an EVALUATION.md matrix row."""
    assert session_type(env) == expected


def test_every_session_type_produced_is_in_the_schema_vocabulary() -> None:
    from yazses.eyeeval import SESSION_TYPES

    cases = [{}, {"XDG_SESSION_TYPE": "x11"},
             {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "GNOME:ubuntu"},
             {"XDG_SESSION_TYPE": "wayland"}]
    for env in cases:
        assert session_type(env) in SESSION_TYPES
    assert collect_provenance().session_type in SESSION_TYPES


# --- the commit SHA, in the layouts git actually produces --------------------------------------


def test_a_loose_ref_resolves(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "refs" / "heads" / "main").write_text(SHA + "\n", encoding="utf-8")
    assert _git_commit(tmp_path) == SHA[:12]


def test_a_detached_head_resolves(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text(SHA + "\n", encoding="utf-8")
    assert _git_commit(tmp_path) == SHA[:12]


def test_a_packed_ref_resolves(tmp_path: Path) -> None:
    """Every `git gc` packs the refs away, and the first version of this answered None."""
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        f"{SHA} refs/heads/main\n"
        "^1111111111111111111111111111111111111111\n",
        encoding="utf-8",
    )
    assert _git_commit(tmp_path) == SHA[:12]


def test_a_linked_worktree_resolves_through_commondir(tmp_path: Path) -> None:
    """A worktree keeps its own HEAD and shares `refs/` — this is the layout a contributor
    working on two branches at once is in, and it answered None until `commondir`."""
    main = tmp_path / "main" / ".git"
    (main / "refs" / "heads").mkdir(parents=True)
    (main / "refs" / "heads" / "topic").write_text(SHA + "\n", encoding="utf-8")
    linked = main / "worktrees" / "wt"
    linked.mkdir(parents=True)
    (linked / "HEAD").write_text("ref: refs/heads/topic\n", encoding="utf-8")
    (linked / "commondir").write_text("../..\n", encoding="utf-8")
    tree = tmp_path / "wt"
    tree.mkdir()
    (tree / ".git").write_text(f"gitdir: {linked}\n", encoding="utf-8")
    assert _git_commit(tree) == SHA[:12]


def test_no_repository_means_none_not_a_guess(tmp_path: Path) -> None:
    assert _git_commit(tmp_path) is None


def test_a_branch_name_is_never_recorded(tmp_path: Path) -> None:
    """A branch is free text a contributor chose; it can carry a name or an employer."""
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/evelyn/private-client-work\n", encoding="utf-8")
    assert _git_commit(tmp_path) is None  # unresolvable ref -> nothing, not the name


def test_a_ref_that_climbs_out_of_the_repository_is_refused(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (tmp_path / "secret").write_text(SHA + "\n", encoding="utf-8")
    (git / "HEAD").write_text("ref: ../secret\n", encoding="utf-8")
    assert _git_commit(tmp_path) is None
