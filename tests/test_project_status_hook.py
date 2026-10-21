"""The site's release status is derived from CHANGELOG.md, so it cannot go stale."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks/project_status.py"

CHANGELOG = """\
# Changelog

## [Unreleased]

### Added — a switched-on feature installs its own libraries ([#545](https://example/545))

Body text with a fake heading inside a fence:

```md
## [9.9.9] - 2099-01-01
### Fixed — not a real entry
```

### Fixed — `yazses update` names a command that works
### Fixed — Mandarin text no longer gains spaces
### Tests — every Head-Pointer state

## [2.43.2] - 2026-10-18

### Fixed — something already released

## [2.43.0-dev.1] - 2026-10-10

## [2.42.0] - 2026-10-04
"""


@pytest.fixture(scope="module")
def hook():
    spec = importlib.util.spec_from_file_location("project_status", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def releases_dir(tmp_path: Path) -> Path:
    (tmp_path / "v2.43.2.md").write_text(
        '---\ntitle: "YazSes v2.43.2 — no more words nobody said"\n'
        'description: "A loud burst is no longer decoded."\n---\n\n# body\n',
        encoding="utf-8",
    )
    return tmp_path


def test_unreleased_entries_are_the_headings_under_unreleased_only(hook):
    log = hook.parse_changelog(CHANGELOG)
    assert [(e.kind, e.text) for e in log.unreleased] == [
        ("Added", "a switched-on feature installs its own libraries (#545)"),
        ("Fixed", "yazses update names a command that works"),
        ("Fixed", "Mandarin text no longer gains spaces"),
        ("Tests", "every Head-Pointer state"),
    ]


def test_a_heading_inside_a_code_fence_is_not_a_release(hook):
    versions = [r.version for r in hook.parse_changelog(CHANGELOG).releases]
    assert "9.9.9" not in versions
    assert versions == ["2.43.2", "2.43.0-dev.1", "2.42.0"]


def test_previews_are_not_reported_as_the_latest_release(hook):
    stable = [r.version for r in hook.parse_changelog(CHANGELOG).stable]
    assert stable == ["2.43.2", "2.42.0"]


def test_status_reads_the_release_note_headline(hook, releases_dir):
    status = hook.build_status(hook.parse_changelog(CHANGELOG), releases_dir)
    latest = status["latest"]
    assert latest["version"] == "2.43.2"
    assert latest["date"] == "2026-10-18"
    assert latest["headline"] == "no more words nobody said"
    assert latest["description"] == "A loud burst is no longer decoded."
    assert latest["note"] == "releases/v2.43.2.html"
    # A release with no note page still appears, just without a link or headline.
    assert status["recent"][1] == {
        "version": "2.42.0", "date": "2026-10-04", "headline": "", "description": "", "note": "",
    }
    assert status["unreleased_count"] == 4
    assert status["unreleased_kinds"] == {"Fixed": 2, "Added": 1, "Tests": 1}


def test_placeholders_are_replaced_and_other_text_is_kept(hook, releases_dir):
    log = hook.parse_changelog(CHANGELOG)
    status = hook.build_status(log, releases_dir)
    page = (
        "intro\n\n<!-- yazses-status:latest -->\n\n<!-- yazses-status:unreleased-summary -->\n\n"
        "<!-- yazses-status:unreleased -->\n\n<!-- yazses-status:recent-releases -->\n\n"
        "<!-- yazses-status:unknown -->\n"
    )
    out = hook.render_placeholders(page, log, status)
    assert "<!-- yazses-status:latest -->" not in out
    assert "**Latest release: [v2.43.2](releases/v2.43.2.md)**, published 2026-10-18" in out
    assert "**4 changes are on `main` and not yet in a release** — Fixed 2 · Added 1 · Tests 1." in out
    # The full list keeps the Markdown links the changelog wrote.
    assert "- a switched-on feature installs its own libraries ([#545](https://example/545))" in out
    assert "| [v2.43.2](releases/v2.43.2.md) | 2026-10-18 | no more words nobody said |" in out
    assert "| v2.42.0 | 2026-10-04 | — |" in out
    assert "<!-- yazses-status:unknown -->" in out


def test_an_empty_unreleased_section_says_so(hook):
    log = hook.parse_changelog("## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n")
    status = hook.build_status(log, Path("/nonexistent"))
    out = hook.render_placeholders(
        "<!-- yazses-status:unreleased-summary -->\n<!-- yazses-status:unreleased -->", log, status
    )
    assert "Everything on `main` has been released." in out
    assert "Nothing is waiting for a release right now." in out


def test_the_real_changelog_yields_a_status_that_matches_pyproject(hook):
    """The parse must keep working on the file it exists for, not only on the fixture."""
    import tomllib

    log = hook.parse_changelog((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    status = hook.build_status(log)
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert status["latest"]["version"] == version
    assert status["latest"]["headline"], "the latest release note has no 'YazSes vX — headline' title"
    assert len(status["recent"]) == hook.RECENT_RELEASES
