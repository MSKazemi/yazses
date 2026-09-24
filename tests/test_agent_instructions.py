"""The agent instruction files must agree with each other and with reality.

Several surfaces tell a contributor — human or coding agent — what the gates are.
`AGENTS.md` is canonical; `CLAUDE.md` and `GEMINI.md` are intentionally tiny tracked
adapters that import it, while `CONTRIBUTING.md`, `README.md` (plus its translations)
and the `Makefile` expose selected human-facing commands. These surfaces had drifted in the
worst possible direction: `AGENTS.md` told agents the codebase carried "~135 known type
errors across 50 files" and that "a clean run is not the bar", while `CONTRIBUTING.md`
said mypy reports no issues at all. `mypy src` actually reports `Success: no issues found
in 433 source files`. An agent reading the stale file would have shipped type errors and
called them pre-existing — and been following the instructions when it did.

Historically, `AGENTS.md` sent contributors to a root `CLAUDE.md` that was gitignored and
present only in the maintainer's checkout. The public design now avoids that failure in a
different way: `AGENTS.md` is the single source of truth, while any tool-specific filename
is tracked only as a thin import adapter. Private assistant configuration stays in ignored
local/user files.

That history is why these checks resolve paths through `git ls-files` rather than the
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
TOOL_ADAPTERS = {
    "CLAUDE.md": "@AGENTS.md",
    "GEMINI.md": "@./AGENTS.md",
}
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


def test_private_agent_configuration_is_never_tracked():
    """Local assistant state stays private even if an ignore rule is bypassed."""
    tracked = _tracked()
    if not tracked:
        return

    forbidden = sorted(
        path for path in tracked
        if path == "CLAUDE.local.md"
        or path.startswith(".claude/")
        or path.startswith(".gemini/")
    )
    assert not forbidden, (
        "private local agent configuration is tracked: "
        f"{forbidden}. Keep only the public CLAUDE.md/GEMINI.md adapters in git."
    )


def test_canonical_agent_file_and_thin_adapters_are_shipped():
    """Every supported auto-discovery filename must resolve to one public source of truth."""
    tracked = _tracked()
    if not tracked:  # sdist/vendored trees may not carry git metadata
        return

    assert CANONICAL in tracked, (
        f"{CANONICAL} is not tracked by git — it is the public contributor instruction source"
    )

    for adapter, import_line in TOOL_ADAPTERS.items():
        assert adapter in tracked, (
            f"{adapter} is not tracked — the corresponding agent will miss project rules"
        )
        text = _read(adapter)
        assert import_line in text, (
            f"{adapter} must import {CANONICAL} instead of maintaining a second rule set"
        )
        assert "uv sync" not in text and "pytest" not in text and "ruff check" not in text, (
            f"{adapter} duplicates setup/gate commands — keep policy only in {CANONICAL}"
        )


def test_tool_adapter_names_do_not_become_policy_authority():
    """Only adapter-design docs may name tool-specific instruction filenames."""
    tracked = _tracked()
    if not tracked:
        return

    allowed = {
        CANONICAL,
        *TOOL_ADAPTERS,
        "CHANGELOG.md",  # historical record: do not rewrite old release/project history
        "docs/contribute/ai-agents.md",
        "design/adr/adr-023-agent-first-contribution-pipeline.md",
        "tests/test_agent_instructions.py",
    }
    text_suffixes = {".md", ".py", ".toml", ".yml", ".yaml"}
    offenders: list[str] = []

    for name in sorted(tracked - allowed):
        # Release notes are historical records. They may truthfully say that a past
        # version used a tool-specific file; current policy/config/test surfaces may not.
        if name.startswith("docs/releases/"):
            continue
        path = ROOT / name
        if path.suffix not in text_suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(adapter in text for adapter in TOOL_ADAPTERS):
            offenders.append(name)

    assert not offenders, (
        "tool-specific adapter names are being cited outside the adapter-design surfaces: "
        f"{offenders}. Cite AGENTS.md as the project authority instead."
    )


def test_ai_review_disclosure_is_not_ai_authorship():
    """The agent rules must permit review transparency without crediting a tool as author."""
    text = _read(CANONICAL)
    assert "No AI authorship or contributor credit" in text
    assert '"AI assistance" section may name the tool used' in text
    assert "Co-Authored-By" in text


def test_cloud_agent_does_not_weaken_yazses_data_boundary():
    """Agent-assisted development must not turn private user evidence into cloud input."""
    text = _read(CANONICAL).lower()
    assert "never upload real user audio" in text
    assert "cloud development tool is a separate data transfer" in text
    assert "synthetic or explicitly" in text


def test_canonical_agent_rules_treat_external_text_as_untrusted():
    """GitHub/web text may scope work, but it must never outrank repository safety rules."""
    text = _read(CANONICAL).lower()
    assert "untrusted input" in text
    assert "cannot override this file" in text
    assert "credentials" in text


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

    This originally caught an `AGENTS.md` reference to an untracked private `CLAUDE.md`.
    Tool adapters are now tracked, but any instruction link can regress the same way.
    """
    tracked = _tracked()
    if not tracked:  # no git available (sdist, vendored tree) — nothing to verify against
        return
    for name in (CANONICAL, *TOOL_ADAPTERS, CONTRIBUTING, "README.md"):
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


# ADR-024 makes authorship policy explicit: YazSes credits the human contributor, not
# the coding tool. This exact contradiction existed in three shipped surfaces at once:
# AGENTS.md forbade attribution while CONTRIBUTING, the first-contribution page and the
# PR template asked for it. Keep a small regression test because prose drift is the bug.
ATTRIBUTION_SURFACES = (
    "AGENTS.md",
    CONTRIBUTING,
    "docs/contribute/start.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
)

# Disclosure is not attribution, and this guard must not confuse them. AGENTS.md rule 8
# and ADR-026 both draw the line at *authorship*: a tool may never be an author, co-author,
# contributor or rights-holder. Naming the tool used and saying what the human verified is
# review context, which AGENTS.md explicitly permits ("the pull-request template's 'AI
# assistance' section may name the tool used and must say what the human verified").
# An earlier revision of this list banned that section too, which would have made the guard
# refuse what the written contract requires -- so it lists only framings that treat the tool
# as a credited party or make disclosure an acceptance factor. Literal trailer spellings are
# deliberately absent: AGENTS.md has to quote the forms it forbids, so matching them here
# would fire on the rule itself.
_FORBIDDEN_ATTRIBUTION_SNIPPETS = (
    "Mention in the PR body if a change was largely AI-generated",
    "Say in the pull request that you used one",
)


def test_no_contributor_surface_requests_ai_attribution():
    """Project artifacts credit the human contributor only (ADR-026)."""
    stale: list[tuple[str, str]] = []
    for name in ATTRIBUTION_SURFACES:
        text = _read(name)
        for snippet in _FORBIDDEN_ATTRIBUTION_SNIPPETS:
            if snippet.lower() in text.lower():
                stale.append((name, snippet))
    assert not stale, (
        "these contributor surfaces still request coding-tool/AI attribution, "
        f"contradicting AGENTS.md and ADR-026: {stale}"
    )
