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
tests never launch anything. The default reuses ``system/browser.py::open_url``, the
hand-off ADR-019 already inventories under *Reached by handing a URL to another program*,
with ``log_url=False`` so its failure path does not write the URL. No new outbound
primitive is added: this module imports neither ``webbrowser`` nor ``subprocess``.

What the default does per platform is the standard library's choice, and it is recorded
here because ADR-031 §3 asks for it to be written down:

* **Linux:** ``webbrowser`` runs ``xdg-open <url>`` as a child process (``BROWSER``, when
  set, is tried first). The URL — and so the text — is in that process's argument list
  while it runs, readable by other local users through ``/proc``. ADR-031 records this
  exposure rather than waving it away; a desktop-portal opener that avoids it needs the
  platform seam the ADR describes, which is not built yet.
* **macOS:** ``webbrowser`` pipes an AppleScript to ``osascript`` on its standard input,
  so the URL is not in an argument list. Python 3.13's script is ``open location``, which
  goes to the scheme's registered app; Python 3.14's sends a URL that is not ``http(s)``
  to the default *browser* application instead (read in both versions' ``webbrowser``
  source), and the browser may ask before it opens the client — unverified on a real Mac.
* **Windows:** ``os.startfile``, which calls ``ShellExecuteW`` in-process.

**Unverified, and said so:** whether each client pre-fills without submitting has not been
observed on a real Claude or Codex install on any platform (ADR-031 §5 requires a
validation row per client and OS). And on Linux, "handed off" means ``xdg-open`` was
started — it cannot tell whether a program is registered for ``claude://``, so a missing
client is reported by the desktop, not here.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from yazses.sendto.targets import Plan, Refusal, plan_handoff

log = logging.getLogger(__name__)

Opener = Callable[[str], bool]

#: Shown when `[sendto] enabled` is false. Names the key, because there is no
#: `yazses features enable` switch for this capability.
DISABLED_MESSAGE = (
    "Send to is off. Turn it on with `enabled = true` under `[sendto]` in config.toml."
)


def default_opener(url: str) -> bool:
    """Hand *url* to the desktop through the inventoried browser hand-off, quietly.

    ``log_url=False`` is the point: ``open_url``'s default failure log names the URL,
    and this URL is the user's dictation.
    """
    from yazses.system.browser import open_url

    return open_url(url, log_url=False)


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
