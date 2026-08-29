"""A backend that is installed but cannot import must not be reported as available.

Found by running the suite on a box with `uv sync --all-extras`, which no CI job
does. `tests/test_backend_availability.py` covers the case where the optional
dependency is absent; this covers the case it cannot see, where the dependency is
present on disk and still fails to import.

That is not a contrived state. `system/deps.py::missing_modules` answers from
`importlib.util.find_spec`, which reports whether a package exists on disk and never
whether importing it succeeds -- deliberately, because the status path must not load
torch. Resemblyzer imports `webrtcvad`, whose first line is `import pkg_resources`,
which setuptools removed in 81.0.0. So on a current setuptools the probe says
"available" while the constructor raises, and the user was shown:

    Voiceprint backend 'resemblyzer' unavailable: backend 'resemblyzer' is
    available. Voiceprint-dependent features stay dormant.

-- a sentence that contradicts itself and drops the only useful detail, the
exception. `recimport/factory.py` already guards exactly this and says so in a
comment; `voiceprint/factory.py` was written from the same shape and never got it.

The tests force the failure rather than requiring the extra, so they run on every
machine including a base install. A test that only runs where the extra happens to
be installed is how this went unnoticed in the first place.
"""
from __future__ import annotations

import logging
from dataclasses import replace

import pytest

from yazses.config import VoiceprintConfig


@pytest.fixture
def installed_but_broken(monkeypatch):
    """Reproduce the all-extras box: on disk for `find_spec`, raising on import.

    Both halves have to be faked, and faking only one proves nothing. On a base
    install `find_spec("resemblyzer")` already returns None, so the probe takes its
    correct "install the extra" branch and never reaches the contradiction; on the
    box where the bug appeared the package is present and only the *import* fails.
    """
    import importlib.util

    import yazses.voiceprint.factory as factory

    def _boom(*_args, **_kwargs):
        raise ModuleNotFoundError("No module named 'pkg_resources'")

    monkeypatch.setattr(
        "yazses.voiceprint.resemblyzer_backend.ResemblyzerEmbedder", _boom,
        raising=False,
    )

    real = importlib.util.find_spec

    def present_on_disk(name, *args, **kwargs):
        if name == "resemblyzer":
            return importlib.util.spec_from_loader("resemblyzer", loader=None)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", present_on_disk)
    return factory


def _warn_text(caplog) -> str:
    return " ".join(r.getMessage() for r in caplog.records)


def test_it_does_not_say_unavailable_and_available_in_one_breath(
    installed_but_broken, caplog
):
    cfg = replace(VoiceprintConfig(), enabled=True, backend="resemblyzer")
    with caplog.at_level(logging.WARNING):
        assert installed_but_broken.build_embedder(cfg) is None
    msg = _warn_text(caplog)
    assert msg, "a failed backend must say something"
    assert "is available" not in msg, f"self-contradictory message: {msg}"


def test_it_reports_the_actual_exception_instead(installed_but_broken, caplog):
    """The exception is the only text that names a fixable cause."""
    cfg = replace(VoiceprintConfig(), enabled=True, backend="resemblyzer")
    with caplog.at_level(logging.WARNING):
        installed_but_broken.build_embedder(cfg)
    assert "pkg_resources" in _warn_text(caplog)


def test_it_names_the_setuptools_remedy_now_that_nothing_pins_it(
    installed_but_broken, caplog
):
    """The exception alone stopped being enough when the pin was removed.

    `pyproject.toml` used to carry `setuptools<81` inside the
    `voiceprint-resemblyzer` extra so this could not happen. That pin had to go:
    `uv.lock` resolves one version per package for the whole workspace, so it held
    the *base* install -- and the shipped .dmg and .exe, which are built from that
    lock -- below the 83.0.0 that patches Dependabot alert #9.

    Removing it makes this failure the *expected* state for anyone who installs the
    backend on a current setuptools, rather than a rare all-extras-box accident. A
    bare `ModuleNotFoundError: pkg_resources` leaves that user to rediscover a cause
    the project already knows, so the message has to carry the fix.
    """
    cfg = replace(VoiceprintConfig(), enabled=True, backend="resemblyzer")
    with caplog.at_level(logging.WARNING):
        installed_but_broken.build_embedder(cfg)
    msg = _warn_text(caplog)
    assert "setuptools<81" in msg, (
        f"the message names no remedy, only the symptom: {msg}"
    )
    assert "ecapa" in msg.lower(), (
        "the message should also point at the default backend, which needs no pin"
    )


def test_it_still_degrades_to_dormant_rather_than_raising(
    installed_but_broken, caplog
):
    """The message changed; the guarantee did not (ADR-011)."""
    cfg = replace(VoiceprintConfig(), enabled=True, backend="resemblyzer")
    with caplog.at_level(logging.WARNING):
        assert installed_but_broken.build_embedder(cfg) is None


def test_a_genuinely_absent_dependency_still_names_its_own_extra(monkeypatch, caplog):
    """The regression above must not cost the case that already worked.

    When the dependency really is missing, the probe knows the remedy and naming it
    is far more useful than the bare ImportError -- and it must name
    `voiceprint-resemblyzer`, never the neighbouring `voiceprint` extra, which is
    speechbrain and cannot supply Resemblyzer.
    """
    import builtins
    import importlib.util

    real_find, real_import = importlib.util.find_spec, builtins.__import__

    def fake_find(name, *args, **kwargs):
        if name == "resemblyzer":
            return None
        return real_find(name, *args, **kwargs)

    def fake_import(name, *args, **kwargs):
        # The constructor has to fail too. Where the extra genuinely installs and
        # works, patching only `find_spec` leaves `build_embedder` returning a live
        # embedder and the message under test is never emitted.
        if name.split(".")[0] == "resemblyzer":
            raise ModuleNotFoundError("No module named 'resemblyzer'",
                                      name="resemblyzer")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    from yazses.voiceprint.factory import build_embedder

    cfg = replace(VoiceprintConfig(), enabled=True, backend="resemblyzer")
    with caplog.at_level(logging.WARNING):
        assert build_embedder(cfg) is None
    msg = _warn_text(caplog)
    assert "`voiceprint-resemblyzer` extra" in msg, msg
    assert "`voiceprint` extra" not in msg.replace("`voiceprint-resemblyzer` extra", "")
