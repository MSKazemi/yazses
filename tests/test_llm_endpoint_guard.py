"""The "nothing leaves the machine" guard on LLM cleanup.

Cleanup's Ollama backend is the **only** path in YazSes that puts transcribed
text on a socket, and `llm_endpoint` is a hand-edited string. `is_loopback_endpoint`
decides, syntactically and before any socket opens, whether that endpoint can
only reach this machine.

The guard shipped wired but with **no test at all** — the function, its call site
and its config field existed only in the git index, so nothing exercised it. A
security control with no test is a comment. These are the cases that actually
decide whether dictated text can leave the machine, including the bypasses the
implementation's own docstring claims to handle.
"""
from __future__ import annotations

import pytest

from yazses.config import DisfluencyConfig
from yazses.postprocess.llm_cleanup import endpoint_is_permitted, is_loopback_endpoint

LOOPBACK = [
    "http://localhost:11434",           # Ollama's own default
    "http://localhost.localdomain:11434",
    "http://LOCALHOST:11434",           # case must not matter
    "http://127.0.0.1:11434",
    "http://127.0.0.1",
    "http://127.1.2.3:11434",           # the whole 127.0.0.0/8 block is loopback
    "http://[::1]:11434",               # IPv6 loopback
    "  http://localhost:11434  ",       # surrounding whitespace
]

REMOTE = [
    "http://evil.com:11434",
    "http://192.168.1.50:11434",        # LAN is still off this machine
    "http://10.0.0.5:11434",
    "http://8.8.8.8",
    "https://api.example.com/v1",
    "http://localhost.evil.com",        # suffix trick, not loopback
    "http://notlocalhost",
]


@pytest.mark.parametrize("endpoint", LOOPBACK)
def test_loopback_endpoints_are_allowed(endpoint: str) -> None:
    assert is_loopback_endpoint(endpoint) is True, f"{endpoint} should be recognised as local"


@pytest.mark.parametrize("endpoint", REMOTE)
def test_remote_endpoints_are_refused(endpoint: str) -> None:
    assert is_loopback_endpoint(endpoint) is False, f"{endpoint} would send text off the machine"


def test_userinfo_bypass_is_refused() -> None:
    """`http://127.0.0.1@evil.com` — the classic trick. `urlsplit` puts userinfo
    outside `hostname`, so the real host is `evil.com`. A naive substring check
    for "127.0.0.1" would pass this and exfiltrate every dictation."""
    assert is_loopback_endpoint("http://127.0.0.1@evil.com") is False
    assert is_loopback_endpoint("http://localhost@evil.com:11434") is False
    assert is_loopback_endpoint("http://localhost:pass@evil.com/api") is False


def test_a_name_that_merely_resolves_to_loopback_is_not_trusted() -> None:
    """Deliberate: resolution is DNS- and attacker-controlled and can change
    between the check and the connect. The guard must be syntactic, so a name it
    cannot classify without DNS is refused rather than looked up."""
    # These commonly resolve to 127.0.0.1 in the wild; the guard must still say no.
    for name in ("http://localtest.me", "http://127.0.0.1.nip.io", "http://vcap.me"):
        assert is_loopback_endpoint(name) is False


def test_malformed_and_empty_endpoints_are_refused() -> None:
    """No host component is not an address at all. Refusing here turns a typo
    into one logged sentence instead of a traceback on every dictation burst."""
    for bad in ("", "   ", "localhost:11434", "not a url", "http://", "/just/a/path", "://x"):
        assert is_loopback_endpoint(bad) is False, f"{bad!r} must not be treated as local"


def test_guard_defaults_to_refusing_on_anything_unexpected() -> None:
    """Fail-closed: the failure mode of this function must be 'do not send'."""
    for weird in ("http://[not-an-ip]", "http://999.999.999.999", "\x00", "http://:11434"):
        assert is_loopback_endpoint(weird) is False


# ---------------------------------------------------------------------------
# The policy layer on top of the classifier
# ---------------------------------------------------------------------------

def test_local_endpoint_is_permitted_without_opting_in() -> None:
    cfg = DisfluencyConfig(llm_endpoint="http://localhost:11434")
    assert endpoint_is_permitted(cfg) is True


def test_remote_endpoint_is_blocked_by_default() -> None:
    """The default must be closed — an offline tool that silently POSTs
    transcribed text to a remote host is the failure this exists to prevent."""
    cfg = DisfluencyConfig(llm_endpoint="http://evil.com:11434")
    assert endpoint_is_permitted(cfg) is False


def test_remote_endpoint_requires_an_explicit_opt_in() -> None:
    """It stays possible on purpose — someone with their own LLM box may want
    it — but only as a deliberate, named choice."""
    cfg = DisfluencyConfig(
        llm_endpoint="http://192.168.1.50:11434", llm_allow_remote_endpoint=True
    )
    assert endpoint_is_permitted(cfg) is True


def test_opt_in_defaults_to_false() -> None:
    """If this ever flips, every existing install starts permitting remote sends
    without the user changing anything."""
    assert DisfluencyConfig().llm_allow_remote_endpoint is False


# ---- encodings a more permissive host parser would open ---------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://0x7f000001:11434",        # hex
        "http://2130706433:11434",        # decimal
        "http://017700000001:11434",      # octal
        "http://127.0.0.1.evil.com",      # loopback as a subdomain label
        "http://evil.com#127.0.0.1",      # fragment
        "http://evil.com/?host=localhost",  # query
        "http://ⓛocalhost:11434",         # circled latin small letter l
        "http://lοcalhost:11434",         # greek omicron for o
    ],
)
def test_numeric_and_homoglyph_encodings_are_not_loopback(endpoint):
    """These are safe today only because `ipaddress.ip_address` refuses them.

    `0x7f000001`, `2130706433` and `017700000001` all *mean* 127.0.0.1 to a C
    resolver, and curl will happily connect to them. Python's parser rejects the lot,
    so the guard falls through to "not loopback" and refuses — correct, but by a
    property of the standard library rather than by an explicit decision here.

    That makes them worth pinning: the obvious future kindness is to accept a
    shorthand like `127.1` (which this guard also refuses, failing safe), and a
    host parser permissive enough for that is permissive enough for these. The
    homoglyphs are the same shape in the other alphabet — they render as
    "localhost" and are not it.

    A regression here does not raise or look wrong. It sends dictated text to
    whoever owns the address, which is why this path already has a documented
    history: it once POSTed transcripts to any host the config named.
    """
    assert is_loopback_endpoint(endpoint) is False


def test_the_ipv4_mapped_form_is_loopback_on_every_supported_python():
    """`::ffff:127.0.0.1` is genuinely local and must NOT be refused.

    Verified rather than assumed: an actual connection attempt to it is *refused*
    rather than routed away, so it reaches 127.0.0.1 on this machine. Listing it
    with the bypasses above would break a working IPv6 setup.

    It is also the reason `is_loopback_endpoint` resolves `ipv4_mapped` itself
    instead of trusting `IPv6Address.is_loopback`. CPython only started counting
    IPv4-mapped addresses as loopback in **3.12**; on 3.11 it answers False. This
    project's matrix spans 3.11 to 3.14, so leaning on the stdlib made a privacy
    guard give two different answers depending on the interpreter — the same
    config accepted on one machine and refused on another. Caught by Windows 3.11
    going red while Windows 3.12 passed, which is the narrowest possible signal.
    """
    assert is_loopback_endpoint("http://[::ffff:127.0.0.1]:11434") is True
