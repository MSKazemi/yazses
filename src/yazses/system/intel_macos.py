"""Intel macOS has a wheel ceiling, and it moves — say so before it bites (#264).

YazSes runs on Intel Macs, but the dependencies it needs have started to stop
publishing ``x86_64`` macOS wheels, and each one that stops takes a Python version
with it. Two facts, both measured against the live index rather than assumed:

* ``onnxruntime`` published no ``x86_64`` macOS wheel after **1.23.2**, which was
  built for ``cp310``–``cp313``. ``faster-whisper`` requires ``onnxruntime``, and
  ``faster-whisper`` is not optional here — so on Intel macOS **the base install
  itself** cannot resolve on Python 3.14.
* ``torch`` published no Intel macOS wheel after **2.4.1** (``cp312``), so the
  extras that pull it in -- ``voiceprint``, and therefore ``[all]`` -- already
  cannot resolve on Python 3.13.

That produces a failure mode nothing else in the product can catch. A user with a
working install on Python 3.13 upgrades Python for unrelated reasons, and YazSes
stops being installable -- not with a message about Intel macOS, but with a
screenful of resolver backtracking that names ``onnxruntime`` and looks like a
YazSes packaging bug. The install has already happened by the time we could speak,
and the *re*-install is the thing that fails, so the only useful moment to say this
is **while it still works**.

Hence a ``doctor`` row rather than a runtime guard: it is advice about the next
upgrade, not a diagnosis of the current one. It is deliberately silent on every
other platform and on Apple silicon, where none of this applies -- a warning that
shows up where it is irrelevant is one people learn to scroll past.

Pure, so it is tested without a Mac: the caller passes the platform, the machine
and the Python version, and gets back a row or ``None``.

Kept beside the numbers it depends on rather than inside ``doctor.py``, because
``tests/test_intel_macos_ceiling.py`` checks these constants against the markers in
``pyproject.toml``. Two copies of the same fact drift; a copy a test compares does
not.
"""
from __future__ import annotations

#: Highest Python minor with an ``onnxruntime`` x86_64 macOS wheel. Beyond this the
#: *base* install cannot resolve, because faster-whisper requires onnxruntime.
BASE_MAX_MINOR = 13

#: Highest Python minor with a ``torch`` Intel macOS wheel. Beyond this the extras
#: that depend on torch -- and so ``[all]`` -- cannot resolve, though base still can.
EXTRAS_MAX_MINOR = 12

#: GitHub Actions' last x86_64 macOS image, and when it goes away (ADR-017). Named
#: here because it is the other half of the same countdown: when the runner goes,
#: the Intel `.dmg` goes with it and pipx is the only Intel path left.
LAST_INTEL_RUNNER = "macos-15-intel"
LAST_INTEL_RUNNER_UNTIL = "August 2027"


def is_intel_mac(sys_platform: str, machine: str) -> bool:
    """Is this an x86_64 Mac? ``sys.platform`` is ``darwin`` on every macOS."""
    return sys_platform == "darwin" and machine == "x86_64"


def ceiling_advice(
    sys_platform: str,
    machine: str,
    version_info: tuple[int, int],
) -> tuple[str, str, str] | None:
    """A ``doctor`` row about the Intel macOS wheel ceiling, or ``None``.

    ``None`` on every non-Intel-Mac, so the row simply does not appear for the
    overwhelming majority of users.

    The status is never ``FAIL``. Whatever this reports, the copy that is running
    *is* running -- it resolved, or the caller could not have imported this module.
    A ``FAIL`` on a working install would be false, and it would train someone to
    disbelieve the next one.
    """
    if not is_intel_mac(sys_platform, machine):
        return None

    major, minor = version_info
    running = f"Python {major}.{minor}"

    if major > 3 or minor > BASE_MAX_MINOR:
        # Reachable if a wheel appears later, or the user built onnxruntime by hand.
        # Not "impossible": saying so would be a claim about a machine we cannot see.
        return (
            "Intel macOS",
            "WARN",
            f"{running} is past the last Python with an onnxruntime x86_64 macOS "
            f"wheel (1.23.2 stops at 3.{BASE_MAX_MINOR}). This install works, but "
            f"`pipx install yazses` on this Python does not — reinstalling or "
            f"upgrading will fail on a resolver error naming onnxruntime, not YazSes. "
            f"Keep a 3.{BASE_MAX_MINOR} interpreter available.",
        )

    if minor > EXTRAS_MAX_MINOR:
        return (
            "Intel macOS",
            "WARN",
            f"{running}: base YazSes resolves, but `yazses[all]` does not — torch "
            f"published no Intel macOS wheel after 2.4.1 (3.{EXTRAS_MAX_MINOR}), so "
            f"the voiceprint extra cannot install here. Everything not needing torch "
            f"works. Upgrading past 3.{BASE_MAX_MINOR} would break the base install "
            f"too.",
        )

    return (
        "Intel macOS",
        "OK",
        f"{running} — within the wheel ceiling (base needs ≤ 3.{BASE_MAX_MINOR}, "
        f"`[all]` needs ≤ 3.{EXTRAS_MAX_MINOR}). Upstream, not YazSes: onnxruntime "
        f"and torch stopped building for Intel macOS.",
    )
