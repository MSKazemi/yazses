"""Shell-command risk classification + confirm gate (pure) — ADR-v2-065.

Assess a dictated command's destructiveness and hold dangerous ones pending a spoken confirm.
Pure and deterministic; terminal-focus detection and any fuzzy classifier live elsewhere.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Ordered (pattern, reason) — first match wins. Irreversible/destructive → "dangerous".
_DANGEROUS = [
    (r"\brm\s+(?:-\w+\s+)*-\w*[rf]\w*", "recursive/forced delete"),
    (r"\brm\s+-\w*[rf]", "recursive/forced delete"),
    (r"\bdd\b[^\n]*\bof=", "raw disk write"),
    (r"\bmkfs\b", "format filesystem"),
    (r"\b(?:shutdown|reboot|halt|poweroff|init\s+0)\b", "power state change"),
    (r"\bgit\s+push\b[^\n]*(?:--force\b|\s-f\b)", "force push"),
    (r"\bgit\s+reset\s+--hard\b", "hard reset (discards changes)"),
    (r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b", "pipe download to shell"),
    (r">\s*/dev/(?:sd|nvme|hd)\w*", "overwrite block device"),
    (r":\(\)\s*\{\s*:\s*\|\s*:", "fork bomb"),
    (r"\bchmod\s+-R\s+0*777\b", "recursive world-writable"),
    (r"\brm\s+-\w*\s+/(?:\s|$)", "delete root"),
]
# Elevated or overwrite-capable but not inherently destructive → "caution".
_CAUTION = [
    (r"\bsudo\b", "runs as root"),
    (r"\bgit\s+clean\s+-\w*[dfx]", "removes untracked files"),
    (r"\btruncate\b", "truncates a file"),
    (r"\bmv\b[^\n]+\s+/\w", "moves into a system path"),
]


@dataclass(frozen=True)
class RiskAssessment:
    """A command's risk ``level`` (safe|caution|dangerous) and a human ``reason``."""
    level: str
    reason: str


def assess_command(text: str) -> RiskAssessment:
    """Classify a dictated shell command's risk. Pure."""
    cmd = (text or "").lower()
    for pat, reason in _DANGEROUS:
        if re.search(pat, cmd):
            return RiskAssessment("dangerous", reason)
    for pat, reason in _CAUTION:
        if re.search(pat, cmd):
            return RiskAssessment("caution", reason)
    return RiskAssessment("safe", "")


class ConfirmGate:
    """Hold a dangerous command until :meth:`confirm`; safe/caution pass straight through. Pure."""

    def __init__(self) -> None:
        self._pending: str | None = None

    @property
    def pending(self):
        """The command awaiting confirmation, or ``None``."""
        return self._pending

    def submit(self, text: str):
        """Return the command to inject now, or ``None`` if it is held pending confirmation."""
        if assess_command(text).level == "dangerous":
            self._pending = text
            return None
        return text

    def confirm(self):
        """Release and return the held command (or ``None`` if nothing is pending)."""
        held, self._pending = self._pending, None
        return held

    def cancel(self) -> None:
        """Discard any held command."""
        self._pending = None
