"""The agent instruction files must agree with each other and with reality.

Five surfaces tell a contributor — human or coding agent — what the gates are:
`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `CONTRIBUTING.md`, `README.md` (plus its
translations) and the `Makefile`. They are hand-maintained and they had drifted in the
worst possible direction: `AGENTS.md` told agents the codebase carried "~135 known type
errors across 50 files" and that "a clean run is not the bar", while `CONTRIBUTING.md`
said mypy reports no issues at all. `mypy src` actually reports `Success: no issues found
in 433 source files`. An agent reading the stale file would have shipped type errors and
called them pre-existing — and been following the instructions when it did.

`AGENTS.md` also sent contributors to a root `CLAUDE.md` for the architecture reference.
That file is deliberately **gitignored** — it carries local configuration — so it exists in
the maintainer's checkout and in no clone anyone else has ever made. The instruction read
fine to the only person who could not observe it failing.

That last point is why these checks resolve paths through `git ls-files` rather than the
filesystem: the question is never "is this file on this disk", it is "does a contributor
receive this file". A test that reads the working tree would have passed on the maintainer's
machine while the reference was broken for everybody else — reproducing the exact bug.

These checks are offline, deterministic, and cheap. They do not run mypy — that is the
`types` target's job. They check the far more fragile thing: that the files do not
contradict each other, and that none of them points at something a contributor cannot see.
"""
from __future__ import annotations

import posixpath
import re
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CANONICAL = "AGENTS.md"
#: GitHub reads the community-health files from `.github/` as readily as from the root,
#: and the root listing was 43 markdown files deep. Named once, because every surface
#: below addresses it by repo-relative path.
CONTRIBUTING = ".github/CONTRIBUTING.md"
#: Every surface that states whether the type checker is clean.
MYPY_SURFACES = ("AGENTS.md", CONTRIBUTING, "README.md", "Makefile")


@lru_cache(maxsize=1)
def _tracked() -> frozenset[str]:
    """Repo-relative paths git actually ships. Empty set if git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    return frozenset(line for line in out.splitlines() if line)


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _translated_readmes() -> list[str]:
    """The translations, as repo-relative paths, at `docs/<code>/index.md`.

    They were `README.<code>.md` at the repo root until the move that gave them
    `hreflang` and `canonical` on the docs site. The count is asserted because a
    glob left pointing at the old location matches nothing, and the two checks that
    iterate this list would then pass by examining no files at all — green, and
    guarding nothing.
    """
    found = [
        p for p in sorted(ROOT.glob("docs/*/index.md"))
        if "yazses-l10n" in p.read_text(encoding="utf-8")
    ]
    assert len(found) > 20, (
        f"expected the translations at docs/<code>/index.md, found {len(found)} — "
        "if they moved again, repoint this glob rather than letting it match nothing"
    )
    return [p.relative_to(ROOT).as_posix() for p in found]


def test_the_canonical_agent_file_is_shipped():
    """`AGENTS.md` is the one instruction file a contributor is guaranteed to get.

    The tool-specific files (`CLAUDE.md`, `GEMINI.md`) are deliberately gitignored as
    local configuration, so this is the only agent brief that travels with a clone.
    """
    assert CANONICAL in _tracked() or not _tracked(), (
        f"{CANONICAL} is not tracked by git — it is the public agents.md contributor "
        "standard and the only agent instruction file that reaches a clone"
    )


def _instruction_links(text: str) -> set[str]:
    """Every repo file this text sends a reader to, in either form it is written.

    Both forms count and both have broken in this repo:

        [docs/architecture.md](docs/architecture.md)   markdown link
        `CLAUDE.md` in the repo root holds ...          backticked reference

    The original dangling pointer was the *second* form, so matching only markdown
    links would reproduce the miss this test exists to prevent.
    """
    linked = re.findall(r"\]\(([A-Za-z0-9_./-]+\.md)\)", text)
    backticked = re.findall(r"`([A-Za-z0-9_./-]+\.md)`", text)
    return set(linked) | set(backticked)


def _candidate_targets(target: str, owner: str) -> set[str]:
    """Repo-relative paths `target` could mean, as written inside `owner`.

    A markdown link resolves against the *linking file's* directory, so once a
    surface moved out of the root (`.github/CONTRIBUTING.md`) its links became
    `../ROADMAP.md` — correct on GitHub, absent from `git ls-files`, which lists
    `ROADMAP.md`. Normalising against the owner's directory is what compares the
    two honestly. A backticked mention is prose rather than a path, so the repo
    root stays a valid reading of a bare name too.
    """
    owner_dir = posixpath.dirname(owner)
    resolved = posixpath.normpath(posixpath.join(owner_dir, target)) if owner_dir else target
    return {resolved, posixpath.normpath(target)}


def test_no_shipped_instruction_file_points_at_something_unshipped():
    """The failure this suite exists to catch, in its general form.

    `AGENTS.md` told contributors to read a root `CLAUDE.md` that no clone contains.
    A gitignored target is worse than a missing one: it resolves on the author's
    machine, so the broken link is invisible to the only person who could fix it.
    """
    tracked = _tracked()
    if not tracked:  # no git available (sdist, vendored tree) — nothing to verify against
        return
    for name in (CANONICAL, CONTRIBUTING, "README.md"):
        for target in _instruction_links(_read(name)):
            assert _candidate_targets(target, name) & tracked, (
                f"{name} links to {target}, which git does not ship — a contributor "
                "who clones this repo cannot open it. Point at a tracked file, or "
                "drop the reference. (If it exists on your disk, it is gitignored.)"
            )


def _claims_known_type_errors(text: str) -> bool:
    """Does this surface tell the reader that type errors are expected and acceptable?"""
    return bool(
        re.search(r"pre-existing (type )?errors?", text, re.I)
        or re.search(r"known (type )?errors?", text, re.I)
        or re.search(r"\d+ known type errors", text, re.I)
    )


def test_no_surface_claims_type_errors_are_expected():
    """`mypy src` reports no issues. Every surface must say the same thing.

    This is prose-level, not a mypy run: the `types` target proves the codebase, this
    proves the *instructions* match it. If mypy ever legitimately carries a backlog
    again, update `CONTRIBUTING.md` and this test together — deliberately, in one PR,
    rather than letting four files drift apart over months.
    """
    lying = [name for name in MYPY_SURFACES if _claims_known_type_errors(_read(name))]
    assert not lying, (
        f"these surfaces still tell contributors that type errors are pre-existing or "
        f"known: {lying}. `uv run mypy src` reports no issues across the source tree — "
        "an agent that believes otherwise will ship type errors and report them as "
        "someone else's. CONTRIBUTING.md holds the correct wording."
    )


def test_translated_readmes_do_not_keep_a_stale_gate_claim():
    """A translation carrying the old claim is the same bug, harder to notice."""
    stale = [name for name in _translated_readmes() if _claims_known_type_errors(_read(name))]
    assert not stale, (
        f"translated READMEs still claim known/pre-existing type errors: {stale} — "
        "the gate block is copied verbatim from README.md, so copy the corrected one across"
    )


#: The workflow that decides whether a PR is green. It is the authority on the gates;
#: every human-facing surface is a copy of it, and copies drift.
CI_WORKFLOW = ".github/workflows/test.yml"
#: Surfaces that quote the lint command to a contributor.
#: `.devcontainer/setup.sh` is here because it is the *first* thing a Codespaces
#: contributor reads, and it was telling them to run `ruff check .` — which exited 1 on a
#: clean checkout over an import-order error in `design/research/verify_refs.py`, outside
#: the `src tests scripts` CI lints. This list is what the check below iterates, so a
#: surface that is not named here is a surface nobody is checking; the banner was drifting
#: for exactly that reason.
LINT_SURFACES = (
    "AGENTS.md", CONTRIBUTING, "README.md", "Makefile", ".devcontainer/setup.sh",
)


def _ruff_targets(text: str) -> list[list[str]]:
    """Every `ruff check <targets>` invocation in a file, as target lists."""
    out = []
    for m in re.finditer(r"ruff check ([A-Za-z0-9_ ./-]+)", text):
        targets = [t for t in m.group(1).split() if not t.startswith("-")]
        if targets:
            out.append(targets)
    return out


def test_every_surface_quotes_the_lint_command_ci_actually_runs():
    """A documented gate weaker than the real one is worse than no gate at all.

    CI and the Makefile lint `src tests scripts`. `AGENTS.md` and both READMEs told
    contributors to lint `src tests` — 12 Python files in `scripts/` were outside the
    command every agent was instructed to run. Following the instructions produced a
    green local check and a red CI, and `AGENTS.md` tells agents in the same breath to
    "run them before claiming anything works", so the false confidence was engineered in.

    The workflow is the authority here; the prose is a copy of it. This asserts the
    copies still match, whatever the targets become.
    """
    ci = _ruff_targets(_read(CI_WORKFLOW))
    assert ci, f"no `ruff check` invocation found in {CI_WORKFLOW} — has the gate moved?"
    expected = set(ci[0])

    surfaces = [*LINT_SURFACES, *_translated_readmes()]
    for name in surfaces:
        for targets in _ruff_targets(_read(name)):
            missing = sorted(expected - set(targets))
            assert not missing, (
                f"{name} tells contributors to run `ruff check {' '.join(targets)}`, but "
                f"{CI_WORKFLOW} runs it over {sorted(expected)} — {missing} would go "
                "unchecked locally and fail in CI. Quote the command CI actually runs."
            )


def test_the_browser_only_contribution_path_is_advertised():
    """The repo ships a Dev Container; for a long time nothing told a newcomer.

    A contributor with no local Python — the single largest group a first-contribution
    campaign reaches — could not tell that docs, config and test changes need no setup
    at all. The environment existed and was invisible.
    """
    assert (ROOT / ".devcontainer" / "devcontainer.json").is_file(), (
        "the Dev Container is gone but README.md still advertises Codespaces"
    )
    assert "codespaces.new" in _read("README.md"), (
        "README.md no longer links the Codespaces one-click path — the Dev Container "
        "only helps people who know it is there"
    )
