"""Speaker-embedder factory (dormancy + graceful degradation).

``build_embedder`` returns ``None`` when ``[voiceprint] enabled = false`` (dormant)
or when the selected backend's library (speechbrain / resemblyzer) is not
installed — :func:`unavailable_message` says which, and what to run — callers treat ``None`` as "no voiceprint available" and stay dormant,
so nothing crashes and no model downloads unless explicitly enabled (ADR-011).
"""
from __future__ import annotations

import logging

from yazses.voiceprint.base import SpeakerEmbedder

log = logging.getLogger(__name__)

#: The YazSes extra that ships each backend. They are alternatives behind different
#: extras, so a remedy must name the one for the backend the user selected.
BACKEND_EXTRAS: dict[str, str] = {
    "ecapa": "voiceprint",
    "resemblyzer": "voiceprint-resemblyzer",
}


def unavailable_message(config, cfg=None) -> str:
    """Why `build_embedder` returned ``None`` for *config*, and what to do — one line.

    Two different causes used to share one sentence that blamed a missing extra and
    told the user to ``uv sync`` the voiceprint extra (a source-checkout command):
    ``[voiceprint]`` simply being off, and the backend's library being absent. The
    remedy for the second comes from :func:`yazses.system.remedy.install_hint`, with
    the Cocktail Filter as the capability whose registry entry installs speechbrain.
    """
    if not getattr(config, "enabled", False):
        return (
            "`[voiceprint] enabled` is false. Set `[voiceprint] enabled = true` in "
            "config.toml, then run `yazses enroll-voice`."
        )
    backend = getattr(config, "backend", "ecapa")
    extra = BACKEND_EXTRAS.get(backend)
    if extra is None:
        return (
            f"`[voiceprint] backend = {backend!r}` is not a known backend; use "
            f"{' or '.join(repr(b) for b in BACKEND_EXTRAS)}."
        )
    from yazses.system.remedy import install_hint

    hint = install_hint(extra, feature="cocktail", cfg=cfg)
    head = f"The {backend!r} voiceprint backend could not load"
    return f"{head}. {hint}" if hint else f"{head}; see the log above for why."


def build_embedder(config) -> SpeakerEmbedder | None:
    """Return a speaker embedder for *config*, or None when dormant/unavailable."""
    if not getattr(config, "enabled", False):
        return None

    backend = getattr(config, "backend", "ecapa")
    try:
        if backend == "ecapa":
            from yazses.voiceprint.ecapa import EcapaEmbedder

            return EcapaEmbedder(config)
        if backend == "resemblyzer":
            from yazses.voiceprint.resemblyzer_backend import ResemblyzerEmbedder

            return ResemblyzerEmbedder(config)
        log.warning("Unknown voiceprint backend %r; voiceprint disabled.", backend)
        return None
    except Exception as exc:
        log.warning(
            "Voiceprint backend %r unavailable: %s. "
            "Voiceprint-dependent features stay dormant.",
            backend, _unavailable_detail(backend, exc),
        )
        return None


def _unavailable_detail(backend: str, exc: Exception) -> str:
    """Explain *why* a backend failed, without misdirecting the user.

    The two backends are alternatives shipped behind *different* extras —
    ``voiceprint`` is speechbrain/ECAPA, ``voiceprint-resemblyzer`` is
    Resemblyzer — so a single blanket "install the `voiceprint` extra" would send
    half the users after a package that cannot supply what they selected. Route
    the message through the shared probe so each case names its own extra.
    """
    try:
        from yazses.system.backends import probe_backend

        adapters = {
            "ecapa": ("yazses.voiceprint.ecapa", ("speechbrain",), BACKEND_EXTRAS["ecapa"]),
            "resemblyzer": (
                "yazses.voiceprint.resemblyzer_backend",
                ("resemblyzer",),
                BACKEND_EXTRAS["resemblyzer"],
            ),
        }
        if backend in adapters:
            adapter, requires, extra = adapters[backend]
            status = probe_backend(
                backend, adapter=adapter, requires=requires, extra=extra
            )
            if status.available:
                # The adapter imported and every dependency the probe knows about
                # is present, so the probe has nothing to report -- and pasting its
                # "is available" onto this caller's "unavailable:" prefix produced a
                # message that contradicted itself in a single sentence, while
                # discarding the one thing that would have helped: the exception.
                #
                # It is reachable, not theoretical. The probe answers from
                # `importlib.util.find_spec`, which reports whether a package is on
                # disk, never whether it imports -- and Resemblyzer pulls in
                # `webrtcvad`, whose first line is `import pkg_resources`, removed
                # from setuptools in 81.0.0. So a correctly installed
                # `voiceprint-resemblyzer` extra raises ModuleNotFoundError on a
                # current setuptools and the user was told the backend was
                # available. `recimport/factory.py` already guards this; the two
                # were written from the same shape and only one got the fix.
                #
                # The remedy is named here rather than left to the traceback,
                # because `pyproject.toml` no longer pins setuptools for this
                # extra and cannot: `uv.lock` resolves one version for the whole
                # workspace, so the pin held every install -- and both shipped
                # bundles, built from that lock -- below the 83.0.0 that patches
                # Dependabot #9. So this is now the *expected* state for anyone who
                # installs the backend on a current setuptools, and a bare
                # ModuleNotFoundError would leave them to rediscover the cause.
                if "pkg_resources" in str(exc):
                    return (
                        f"{exc} -- `resemblyzer` needs `webrtcvad`, which imports "
                        "`pkg_resources`; setuptools removed it in 81.0.0. Run "
                        '`pip install "setuptools<81"` in this environment, or use '
                        "the default `[voiceprint] backend = \"ecapa\"`, which "
                        "needs no such pin."
                    )
                return str(exc)
            if status.implemented or status.missing:
                return status.message
    except Exception:  # pragma: no cover - diagnostics must never mask the real error
        pass
    return str(exc)
