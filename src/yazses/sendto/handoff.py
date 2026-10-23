"""Hand a planned "send to" URL to the desktop — the one impure step (ADR-031).

:mod:`yazses.sendto.targets` decides the client, the URL and the refusals. This module
opens the URL and reports what happened, under two rules that do not bend:

* **The text never reaches a log.** Not at INFO, not on failure, not in a traceback.
  What is logged is the target and the text's *length*. The URL is the text,
  percent-encoded, so it is treated exactly like the text.
* **Nothing is sent.** The client opens a new conversation with the text in the prompt
  box; pressing Enter there is the user's act, never this module's.

## The opener seam

The opener is any ``Callable[[str], bool]`` — "was the URL handed off?" — injected so the
tests never launch anything. The default goes through the platform layer's
:class:`~yazses.platform.base.UrlOpener` (``platform.get_url_opener()``), one
implementation per OS beside the ``FileOpener`` seam, as ADR-031 §3 asks. Before calling
it, the default checks the URL's scheme against the closed target table once more, so
even a caller that bypassed :func:`plan_handoff` could not open anything else. This
package imports neither ``subprocess`` nor ``webbrowser`` nor ``os``; the one process or
OS call happens behind the seam.

What each backend does, and the local exposure each leaves (ADR-031 §3 asks for it to be
written down):

* **Linux and the BSDs:** ``xdg-open <url>`` as a child process — one argv element, no
  shell, its output discarded. While it runs, the URL — and so the text — is in its
  argument list, readable through ``/proc`` by the user's own processes and, unless
  ``/proc`` is mounted with ``hidepid=``, by every local user. A client that the hand-off
  *starts* usually gets the URL as an argument too, for as long as it runs.
* **macOS:** ``NSWorkspace.openURL_`` in-process, so no argument list holds the URL; if
  PyObjC cannot be imported, ``open <url>``, which does put it in one briefly.
  Unverified on a real Mac.
* **Windows:** ``os.startfile``, which calls ``ShellExecuteW`` in-process; the client the
  shell starts gets the URL as its ``%1`` argument.

**Unverified, and said so:** whether each client pre-fills without submitting has not been
observed on a real Claude or Codex install on any platform (ADR-031 §5 requires a
validation row per client and OS). On Linux, "handed off" means ``xdg-open`` exited 0 or
was still running after a few seconds; a status such as 4 (no program registered for the
scheme) is reported as a failed hand-off.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from yazses.sendto.targets import TARGETS, Plan, Refusal, plan_handoff

log = logging.getLogger(__name__)

Opener = Callable[[str], bool]

#: Shown when `[sendto] enabled` is false. Names the switch and the key it writes, so a
#: user who edits config.toml by hand is told the same thing.
DISABLED_MESSAGE = (
    "Send to is off. Turn it on with `yazses features enable sendto` (it sets "
    "`enabled = true` under `[sendto]` in config.toml), then `yazses restart` for the "
    "spoken phrases."
)


#: The only schemes the default opener hands to the desktop: those of the closed table.
_TARGET_SCHEMES: frozenset[str] = frozenset(t.scheme for t in TARGETS.values())


def default_opener(url: str) -> bool:
    """Hand *url* to the program registered for its scheme, through the platform seam.

    Refuses (returns False, opens nothing) a URL whose scheme is not one of the closed
    target table's — the allow-list; the platform seam's own web-scheme refusal is the
    deny-list behind it. Any exception from the platform layer (no backend for this OS,
    no program registered, the opener failing) propagates to :func:`hand_off`, which
    reports it by type only.
    """
    scheme = url.partition("://")[0].lower() if "://" in url else ""
    if scheme not in _TARGET_SCHEMES:
        log.warning("Send to: refused to open a URL outside the target table.")
        return False
    from yazses.platform.factory import get_url_opener

    get_url_opener().open_url(url)
    return True


@dataclass(frozen=True)
class HandoffResult:
    """What a hand-off did. Safe to log, return over IPC and show: it holds no text."""

    ok: bool
    target: str          # the slug asked for, as given (may be unknown)
    label: str           # the client's name, or the slug when unknown
    chars: int
    reason: str = ""     # a Refusal value, "open_failed" or "disabled"; "" on success
    message: str = ""    # one sentence for the user

    def as_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "target": self.target, "label": self.label,
                "chars": self.chars, "reason": self.reason, "message": self.message}


def _refused(plan: Plan, target_name: str, *, staged: bool) -> HandoffResult:
    label = plan.target.label if plan.target is not None else target_name
    assert plan.refusal is not None
    if plan.refusal is Refusal.EMPTY:
        message = ("Nothing to send — nothing is staged." if staged
                   else "Nothing to send — dictate something first.")
    else:
        message = f"Not sent to {label}: {plan.detail}."
        if staged and plan.refusal in (Refusal.TOO_LONG, Refusal.URL_TOO_LONG,
                                       Refusal.INVALID_TEXT):
            message += " The text is still in the staged buffer."
    return HandoffResult(ok=False, target=target_name, label=label, chars=plan.chars,
                         reason=plan.refusal.value, message=message)


def hand_off(
    target_name: str,
    text: str,
    *,
    opener: Opener | None = None,
    staged: bool = False,
) -> HandoffResult:
    """Open *target_name* with *text* pre-filled, or refuse and say why.

    ``staged`` only shapes the wording (where the text still is after a refusal). The
    opener is called at most once, and only with a URL :func:`plan_handoff` built from
    the closed target table. Any exception it raises is caught and reported by type —
    an exception's message can quote its argument, and its argument is the text.
    """
    plan = plan_handoff(target_name, text)
    if not plan.ok:
        # The slug from the closed table, never the name as typed: a CLI argument is
        # free text, and a slip of the fingers could put a prompt in that position.
        log.info("Send to %s: refused (%s), %d character(s).",
                 plan.target.slug if plan.target is not None else "<unknown target>",
                 plan.refusal.value if plan.refusal else "?", plan.chars)
        return _refused(plan, target_name, staged=staged)

    assert plan.target is not None
    label = plan.target.label
    open_fn = opener if opener is not None else default_opener
    try:
        handed = bool(open_fn(plan.url))
    except Exception as exc:  # noqa: BLE001 — never let the text reach a traceback
        log.warning("Send to %s: the opener failed (%s), %d character(s); nothing sent.",
                    plan.target.slug, type(exc).__name__, plan.chars)
        handed = False
    if not handed:
        log.info("Send to %s: could not hand off %d character(s).",
                 plan.target.slug, plan.chars)
        return HandoffResult(
            ok=False, target=plan.target.slug, label=label, chars=plan.chars,
            reason="open_failed",
            message=(f"Could not open {label} — is the {label} desktop app installed? "
                     "Nothing was sent."),
        )
    log.info("Send to %s: handed off %d character(s), pre-filled and not sent.",
             plan.target.slug, plan.chars)
    return HandoffResult(
        ok=True, target=plan.target.slug, label=label, chars=plan.chars,
        message=(f"Opened {label} with {plan.chars:,} characters pre-filled. Review it "
                 "there and press Enter yourself — YazSes did not send it."),
    )


def disabled_result(target_name: str) -> HandoffResult:
    """The answer when `[sendto] enabled` is false. Nothing is planned or opened."""
    return HandoffResult(ok=False, target=target_name, label=target_name, chars=0,
                         reason="disabled", message=DISABLED_MESSAGE)
