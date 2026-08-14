"""``open_url`` must answer a bool, never raise, and never open anything itself here.

The trays call this from a menu click. An exception there kills the click silently on
pystray/rumps and prints a traceback into the Qt loop on Linux; either way the user sees
a menu that did nothing, which is the failure this whole "return the handoff" contract
exists to prevent.
"""

from __future__ import annotations

from yazses.system.browser import open_url


def test_a_successful_open_reports_true():
    opened: list[str] = []

    def _fake(url: str) -> bool:
        opened.append(url)
        return True

    assert open_url("https://example.test/docs", opener=_fake) is True
    assert opened == ["https://example.test/docs"]


def test_no_browser_found_reports_false():
    """``webbrowser.open`` returns False when it cannot find one — not an exception."""
    assert open_url("https://example.test/", opener=lambda _url: False) is False


def test_a_raising_opener_is_contained():
    def _boom(_url: str) -> bool:
        raise RuntimeError("no display")

    assert open_url("https://example.test/", opener=_boom) is False


def test_an_empty_url_is_refused_without_calling_the_opener():
    calls: list[str] = []
    assert open_url("", opener=lambda u: calls.append(u) or True) is False
    assert calls == []
