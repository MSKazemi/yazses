"""`scripts/check-outbound-links.py` must be quiet about everything but real death.

The value of this checker is entirely in what it *declines* to report. A link
check that surfaces publisher bot-blocks gets muted within a week, and a muted
check is worse than no check, because its silence then means nothing. So the
status policy is the thing worth pinning, not the happy path.

Fully offline, like the rest of the suite: every test drives the pure functions or
stubs the one network seam (`status_of`).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-outbound-links.py"


def _load():
    """Import by path -- the filename is not a valid module name."""
    spec = importlib.util.spec_from_file_location("check_outbound_links", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load()


class TestExtractLinks:
    def test_finds_markdown_links(self):
        text = "see [the docs](https://example.net/a) for more"
        assert mod.extract_links(text) == {"https://example.net/a"}

    def test_finds_raw_html_href(self):
        """The contributor wall is generated HTML, not markdown."""
        text = '<a href="https://github.com/someone" title="Translation">x</a>'
        assert mod.extract_links(text) == {"https://github.com/someone"}

    def test_finds_autolinks(self):
        """The citation blocks use angle-bracket autolinks."""
        text = "Ardebili, M. (2026). <https://arxiv.org/abs/2607.28878>"
        assert mod.extract_links(text) == {"https://arxiv.org/abs/2607.28878"}

    def test_strips_the_fragment(self):
        """A dead anchor is a different check; the resource is the same URL."""
        text = "[x](https://example.net/page#section)"
        assert mod.extract_links(text) == {"https://example.net/page"}

    def test_strips_punctuation_the_prose_leaked_in(self):
        text = "see <https://example.net/a>, and <https://example.net/b>."
        assert mod.extract_links(text) == {
            "https://example.net/a",
            "https://example.net/b",
        }

    def test_keeps_balanced_parentheses_in_the_url(self):
        """Elsevier DOIs embed a pair, and the naive regex truncated them.

        Found by running this checker against the repo for the first time: it
        reported `https://doi.org/10.1016/S0020-7373(86` as a 404. The real DOI
        resolves and the page renders it correctly — only the extractor was
        broken, which is the phantom finding that destroys trust in a checker.
        """
        text = "[doi:10.1016/S0020-7373(86)80049-9](https://doi.org/10.1016/S0020-7373(86)80049-9) — *measured*"
        assert mod.extract_links(text) == {
            "https://doi.org/10.1016/S0020-7373(86)80049-9"
        }

    def test_stops_at_a_markdown_link_title(self):
        """`[x](url "title")` -- the title is not part of the URL."""
        text = '[x](https://example.net/a "the title")'
        assert mod.extract_links(text) == {"https://example.net/a"}

    def test_ignores_relative_links(self):
        """Internal links are mkdocs' job and are already checked by --strict."""
        assert mod.extract_links("[x](../features.md) [y](#anchor)") == set()


class TestStatusPolicy:
    @pytest.mark.parametrize("status", [404, 410])
    def test_only_these_are_dead(self, status):
        assert status in mod.DEAD

    @pytest.mark.parametrize(
        "status,why",
        [
            (403, "Cloudflare bot block -- 40+ live citations answered 403"),
            (429, "rate limiting, usually caused by the checker's own parallelism"),
            (500, "the remote having a bad minute"),
            (503, "maintenance"),
            (0, "DNS/TLS/timeout -- indistinguishable from a flaky runner"),
            (200, "alive"),
            (301, "moved, and urllib followed it"),
        ],
    )
    def test_everything_else_is_ignored(self, status, why):
        assert status not in mod.DEAD, why


class TestSkippedHosts:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/foo",
            "https://www.example.com/",
            "http://localhost:8000/x",
        ],
    )
    def test_reserved_documentation_hosts_are_placeholders(self, url):
        assert mod.is_skipped(url)

    def test_real_hosts_are_not_skipped(self):
        assert not mod.is_skipped("https://github.com/MSKazemi/yazses")


class TestCheck:
    def test_a_404_is_reported_with_the_files_that_link_it(self, monkeypatch):
        monkeypatch.setattr(mod, "status_of", lambda url, **kw: 404)
        where = {"https://example.net/gone": {"docs/a.md", "docs/b.md"}}
        findings = mod.check(where, workers=2)
        assert len(findings) == 1
        assert findings[0].status == 404
        assert findings[0].files == ["docs/a.md", "docs/b.md"]

    def test_a_403_is_not_reported(self, monkeypatch):
        monkeypatch.setattr(mod, "status_of", lambda url, **kw: 403)
        assert mod.check({"https://dl.acm.org/doi/10.1145/x": {"docs/a.md"}}) == []

    def test_a_parallel_404_that_recovers_serially_is_not_reported(self, monkeypatch):
        """The serial re-check exists because the parallel pass provokes limits.

        Eight github.com URLs answered 429 in the first real sweep purely from
        concurrency and were all 200 when retried. The same shape can produce a
        transient 404 behind a proxy, so a finding must survive a calm retry.
        """
        calls = {"n": 0}

        def flaky(url, **kw):
            calls["n"] += 1
            return 404 if calls["n"] == 1 else 200

        monkeypatch.setattr(mod, "status_of", flaky)
        assert mod.check({"https://example.net/x": {"docs/a.md"}}) == []
        assert calls["n"] == 2, "the serial re-check did not happen"

    def test_skipped_hosts_are_never_requested(self, monkeypatch):
        def explode(url, **kw):  # pragma: no cover - must not be called
            raise AssertionError(f"requested a placeholder host: {url}")

        monkeypatch.setattr(mod, "status_of", explode)
        assert mod.check({"https://example.com/x": {"docs/a.md"}}) == []


def test_the_published_surfaces_are_actually_covered():
    """A glob that matches nothing passes silently -- the #63 lesson."""
    collected = mod.collect()
    assert collected, "collected no outbound links at all"
    files = {f for files in collected.values() for f in files}
    assert any(f.startswith("docs/") for f in files)
    assert "README.md" in files
