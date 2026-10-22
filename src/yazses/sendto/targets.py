"""Which client, which URL, and when to refuse: the pure half of "send to" (ADR-031).

"Send to Claude" puts the text the user dictated into a new conversation in a desktop AI
client **pre-filled for review**. The client sends it only when the user presses Enter;
YazSes never does. This module decides everything about that hand-off that can be decided
without touching the desktop:

* **The targets are a closed table.** ``claude``, ``claude-code`` and ``codex``, each a
  custom URL scheme that the operating system resolves to a locally installed program.
  The user cannot configure a URL, because a configurable template is a configurable
  exfiltration endpoint, and there is **no** ``https://`` fallback: a web URL would carry
  the text to a server in the request that opens the page, before anyone has reviewed it.
* **Limits are refusals, not truncation.** A truncated prompt sent to an agent is a
  different prompt. Text over the target's limit is refused with the length and the limit.
* **The spoken trigger is one fixed phrase per target**, anchored at both ends (the
  decider's answer of 2026-10-23): "send to Claude", "send to Claude Code", "send to
  Codex". Nothing else claims an utterance.
* **Which text.** The staged buffer when staged mode is on, otherwise the last burst.

Pure and dependency-free: no I/O, no logging, no clock. The opener that actually hands the
URL to the desktop is injected by :mod:`yazses.sendto.handoff`.

The percent-encoding is hand-rolled rather than taken from ``urllib.parse``, for the reason
``system/report.py::_percent_encode`` gives: ADR-019's egress scan treats any ``urllib``
import as a network primitive, and registering this module in the inventory would claim it
can reach the network. The tests pin the result against ``urllib.parse.quote``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


@dataclass(frozen=True)
class Target:
    """One desktop client "send to" can hand text to."""

    slug: str        # the CLI name: `yazses send-to <slug>`
    label: str       # what the user is told: "Claude", "Claude Code", "Codex"
    scheme: str      # a custom scheme the OS resolves to a local program — never http(s)
    path: str        # everything between `scheme://` and `?`
    param: str       # the query parameter that carries the text
    max_chars: int   # longer text is refused, never cut

    def url_for(self, encoded: str) -> str:
        """The hand-off URL for already percent-encoded text."""
        return f"{self.scheme}://{self.path}?{self.param}={encoded}"


#: Claude's documented cut-off: "text cut at about 14,000 characters" (support article
#: "Open Claude Desktop with a link", accessed 2026-10-22). Refused at the limit rather
#: than near it, since the vendor's own figure is approximate.
CLAUDE_MAX_CHARS = 14_000

#: Codex documents no limit for `prompt`. An undocumented limit is not "no limit", so the
#: narrowest safe choice is the same ceiling as Claude's — an engineering choice, not a
#: vendor figure, and the first thing to revisit once a real Codex app has been tried.
CODEX_MAX_CHARS = 14_000

#: The longest URL handed to the desktop, after encoding. On Linux the URL travels as one
#: argument to `xdg-open`, and the kernel caps a single argument at 128 KiB
#: (MAX_ARG_STRLEN); Windows caps a whole command line at 32,767 characters. A character
#: limit alone does not bound this: one emoji is twelve characters once percent-encoded, so
#: 14,000 of them would be a 168,000-character URL. Refusing past 32,000 keeps every
#: platform's opener inside its documented ceiling, at the cost of refusing long text in
#: non-Latin scripts sooner — which the refusal message says, with both numbers.
MAX_URL_CHARS = 32_000

#: The closed list. Read-only on purpose: nothing at runtime may add a destination.
TARGETS: MappingProxyType[str, Target] = MappingProxyType({
    "claude": Target("claude", "Claude", "claude", "claude.ai/new", "q", CLAUDE_MAX_CHARS),
    "claude-code": Target(
        "claude-code", "Claude Code", "claude", "code/new", "q", CLAUDE_MAX_CHARS
    ),
    "codex": Target("codex", "Codex", "codex", "new", "prompt", CODEX_MAX_CHARS),
})

#: Schemes that would make the hand-off a transmission rather than a local hand-over. The
#: table above must never use one; a test holds it to that.
FORBIDDEN_SCHEMES = frozenset({"http", "https", "ftp", "file", "data", "javascript"})

#: RFC 3986 unreserved characters — the only ones a query value carries literally. The
#: same set `urllib.parse.quote(value, safe="")` leaves alone.
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)

#: C0 controls (bar tab, newline and carriage return) and DEL. Dictation never produces
#: them; text passed on the command line can. A NUL in particular is where a client that
#: decodes the query into a C string would silently stop — a truncation by another name.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: The spoken trigger. Whole utterance, anchored at both ends, with an optional final
#: full stop or exclamation mark (Whisper punctuates). "Claude Code" is tried before
#: "Claude" so the longer name wins.
_PHRASE_RE = re.compile(
    r"^\s*send\s+to\s+(claude\s+code|claude|codex)\s*[.!]?\s*$", re.IGNORECASE
)


class Refusal(Enum):
    """Why a hand-off was not attempted. Each has a message; none carries the text."""

    UNKNOWN_TARGET = "unknown_target"
    EMPTY = "empty"
    TOO_LONG = "too_long"
    URL_TOO_LONG = "url_too_long"
    INVALID_TEXT = "invalid_text"


@dataclass(frozen=True)
class Plan:
    """The outcome of :func:`plan_handoff`: a URL to open, or a reason not to.

    ``url`` contains the text, percent-encoded. It is meant for the opener and nothing
    else — never for a log line or a notification.
    """

    target: Target | None
    chars: int
    url: str = ""
    refusal: Refusal | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.refusal is None


@dataclass(frozen=True)
class TextChoice:
    """Which text a hand-off uses, and where it came from (``staged`` or ``last_burst``)."""

    text: str
    source: str


def target_names() -> tuple[str, ...]:
    """The CLI names, in table order: ``("claude", "claude-code", "codex")``."""
    return tuple(TARGETS)


def resolve_target(name: str) -> Target | None:
    """The target called *name*, or ``None``. Case and surrounding space are ignored.

    Only the exact slugs match — no prefixes, no aliases — so a typo is refused rather
    than guessed at.
    """
    return TARGETS.get((name or "").strip().lower())


def parse_send_phrase(utterance: str) -> str | None:
    """The target slug a whole spoken utterance names, or ``None``.

    ``"Send to Claude."`` → ``"claude"``; ``"send to Claude Code"`` → ``"claude-code"``;
    ``"send to Codex"`` → ``"codex"``. Anything more or less is ordinary dictation:
    ``"please send to Claude"``, ``"send to Claude the draft"`` and ``"I will send to
    Claude tomorrow"`` all return ``None``, because an unanchored match would take a
    sentence the user meant to type and hand it off instead.
    """
    match = _PHRASE_RE.match(utterance or "")
    if match is None:
        return None
    name = " ".join(match.group(1).lower().split())
    return "claude-code" if name == "claude code" else name


def percent_encode(value: str) -> str:
    """Percent-encode *value* for a URL query value: UTF-8, everything but unreserved.

    Newlines, ``&``, ``#``, ``=``, ``+``, ``%``, spaces, quotes, right-to-left marks and
    every non-ASCII character are encoded, so no text can end the parameter early, start
    a second one, or add a fragment. Raises ``UnicodeEncodeError`` on a lone surrogate,
    which is what ``sys.argv`` carries for bytes that are not valid UTF-8.
    """
    out: list[str] = []
    for char in value:
        if char in _UNRESERVED:
            out.append(char)
        else:
            out.extend(f"%{byte:02X}" for byte in char.encode("utf-8"))
    return "".join(out)


def plan_handoff(target_name: str, text: str) -> Plan:
    """Decide whether *text* can be handed to *target_name*, and build the URL if so.

    Outer whitespace is trimmed (a continuation burst carries a leading space); nothing
    else about the text is changed. Every refusal leaves the text exactly where it was.
    """
    target = resolve_target(target_name)
    if target is None:
        return Plan(
            target=None, chars=0, refusal=Refusal.UNKNOWN_TARGET,
            detail=(f"there is no target called {target_name!r}; choose one of "
                    f"{', '.join(target_names())}"),
        )
    body = (text or "").strip()
    chars = len(body)
    if not body:
        return Plan(target=target, chars=0, refusal=Refusal.EMPTY,
                    detail="there is no text to send")
    if _CONTROL_RE.search(body):
        return Plan(target=target, chars=chars, refusal=Refusal.INVALID_TEXT,
                    detail="the text contains control characters")
    if chars > target.max_chars:
        return Plan(
            target=target, chars=chars, refusal=Refusal.TOO_LONG,
            detail=(f"{chars:,} characters is over {target.label}'s limit of "
                    f"{target.max_chars:,}; nothing was cut"),
        )
    try:
        encoded = percent_encode(body)
    except UnicodeEncodeError:
        return Plan(target=target, chars=chars, refusal=Refusal.INVALID_TEXT,
                    detail="the text is not valid Unicode")
    url = target.url_for(encoded)
    if len(url) > MAX_URL_CHARS:
        return Plan(
            target=target, chars=chars, refusal=Refusal.URL_TOO_LONG,
            detail=(f"{chars:,} characters encode to a {len(url):,}-character link, over "
                    f"the {MAX_URL_CHARS:,} the desktop can be handed safely; nothing was "
                    "cut (text in non-Latin scripts reaches this sooner)"),
        )
    return Plan(target=target, chars=chars, url=url)


def choose_text(*, staged_enabled: bool, staged_text: str, last_burst: str) -> TextChoice:
    """The text a hand-off without explicit text uses (ADR-031 §1).

    With staged mode on, the staged buffer and nothing else: an empty buffer is an empty
    hand-off, refused, rather than a silent fall-back to an older burst the user is no
    longer looking at. With staged mode off, the last dictation burst.
    """
    if staged_enabled:
        return TextChoice(text=staged_text or "", source="staged")
    return TextChoice(text=last_burst or "", source="last_burst")
