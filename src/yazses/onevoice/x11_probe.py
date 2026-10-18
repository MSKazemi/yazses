"""Read-only X11 window identity feasibility probe for OneVoice issue #600.

A window ID / PID / WM_CLASS is not the identity of an editable field. This
experiment never reports a verified text target and cannot perform an action.
No X11 session, xdotool, microphone, GUI, network or permission is required for
import or pure tests. Users must explicitly supply numeric window IDs.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum


class ProbeStatus(str, Enum):
    OBSERVED = "window_observed_field_unverified"
    UNSUPPORTED_SESSION = "x11_session_required"
    UNAVAILABLE = "window_identity_unavailable"
    INVALID_WINDOW_ID = "invalid_window_id"
    STALE_PIN = "window_identity_changed"


@dataclass(frozen=True)
class WindowIdentity:
    """Ephemeral X11 identity; never sufficient authorization to type."""

    window_id: int
    process_id: int
    wm_class: str

    def __post_init__(self) -> None:
        if not (0 < self.window_id <= 0xFFFFFFFF):
            raise ValueError("invalid X11 window ID")
        if self.process_id <= 0 or not self.wm_class.strip():
            raise ValueError("incomplete window identity")


@dataclass(frozen=True)
class ProbeResult:
    status: ProbeStatus
    identity: WindowIdentity | None = None
    def __post_init__(self) -> None:
        if (self.status is ProbeStatus.OBSERVED) != (self.identity is not None):
            raise ValueError("observed result requires identity; refusals have none")

    @property
    def field_verified(self) -> bool:
        """Hard-coded to false: X11 window metadata proves no editable field."""
        return False


def parse_window_id(raw: str) -> int | None:
    """Accept positive decimal or 0x-prefixed X11 IDs; reject ambiguous strings."""
    if not isinstance(raw, str) or not raw:
        return None
    if raw.startswith("0x") or raw.startswith("0X"):
        digits, base = raw[2:], 16
    else:
        digits, base = raw, 10
    allowed = "0123456789abcdefABCDEF" if base == 16 else "0123456789"
    if not digits or any(character not in allowed for character in digits):
        return None
    try:
        parsed = int(digits, base)
    except ValueError:
        return None
    if not (0 < parsed <= 0xFFFFFFFF):
        return None
    return parsed


def _read(
    command: list[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess],
) -> str | None:
    """Read an xdotool property and drop stderr to avoid leaking UI contents."""
    try:
        result = runner(command, capture_output=True, text=True, timeout=1.0, check=False)
    except (OSError, subprocess.TimeoutExpired, ValueError, RuntimeError):
        return None
    if result.returncode != 0 or not isinstance(result.stdout, str):
        return None
    result_text = result.stdout.strip()
    return result_text if result_text else None


def probe_window(
    raw_window_id: str,
    *,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> ProbeResult:
    """Read only one *explicit* X11 window ID; don't enumerate/activate windows.

    A second PID read detects some ID reuse/change races. It does not make the
    result action-safe: the probe deliberately does not resolve the editor field.
    """
    window_id = parse_window_id(raw_window_id)
    if window_id is None:
        return ProbeResult(ProbeStatus.INVALID_WINDOW_ID)
    if env is None:
        env = os.environ
    if (not env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")
            or env.get("XDG_SESSION_TYPE", "x11").lower() != "x11"):
        return ProbeResult(ProbeStatus.UNSUPPORTED_SESSION)
    if which("xdotool") is None:
        return ProbeResult(ProbeStatus.UNAVAILABLE)

    sid = str(window_id)
    first_pid = _read(["xdotool", "getwindowpid", sid], runner=runner)
    wm_class = _read(["xdotool", "getwindowclassname", sid], runner=runner)
    second_pid = _read(["xdotool", "getwindowpid", sid], runner=runner)
    if first_pid is None or second_pid is None or wm_class is None:
        return ProbeResult(ProbeStatus.UNAVAILABLE)
    if not first_pid.isdecimal() or not second_pid.isdecimal():
        return ProbeResult(ProbeStatus.UNAVAILABLE)
    if first_pid != second_pid or int(first_pid) == 0:
        return ProbeResult(ProbeStatus.UNAVAILABLE)
    # Keep the WM_CLASS internally only. CLI never prints it: the class can
    # reveal installed/private software, even though no text content is read.
    return ProbeResult(
        ProbeStatus.OBSERVED,
        WindowIdentity(window_id, int(first_pid), wm_class),
    )


def revalidate_pin(
    pinned: WindowIdentity,
    *,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> ProbeResult:
    """Return stale if observable identity changed; NEVER certify an editor field."""
    observed = probe_window(
        str(pinned.window_id), env=env, which=which, runner=runner,
    )
    if observed.status is not ProbeStatus.OBSERVED:
        return observed
    if observed.identity != pinned:
        return ProbeResult(ProbeStatus.STALE_PIN)
    return observed


def main(argv: list[str] | None = None) -> int:
    """Human-driven dry-run research command, no audio, focus or keyboard writes."""
    parser = argparse.ArgumentParser(description="Read-only OneVoice X11 identity probe")
    parser.add_argument("--window-a", required=True, help="Explicit numeric window ID A")
    parser.add_argument("--window-b", required=True, help="Explicit numeric window ID B")
    args = parser.parse_args(argv)
    a = parse_window_id(args.window_a)
    b = parse_window_id(args.window_b)
    if a is None or b is None or a == b:
        print("selection: invalid_or_duplicate_window_ids")
        return 2
    results = (
        ("A", probe_window(str(a))),
        ("B", probe_window(str(b))),
    )
    for label, result in results:
        print(f"{label}: {result.status.value}; exact_field=unverified")
    if all(result.status is ProbeStatus.OBSERVED for _, result in results):
        print("result: two_windows_observed; routing_and_insertion_not_authorized")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
