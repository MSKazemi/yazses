"""PySide6 stays out of the base install.

Qt is 648 MB -- it was 59% of a 1.1 GB install -- and it exists for exactly two
desktop features (the voice-activity overlay and the system tray). Every headless
install paid for it and could use none of it: servers, containers, CI, and anyone who
only runs `yazses transcribe`, which never imports it.

Moving it to the `desktop` extra is easy to undo by accident -- one line in
`pyproject.toml` and the weight is back with nothing failing. These tests are the thing
that fails.

They also pin the two ways the move could silently break a user:
  * the Snap must stage PySide6 explicitly, because a snap can NEVER pip-install at
    runtime (read-only squashfs + PEP 668), so an omission there removes both features
    for the life of the revision; and
  * every documented install path must still ask for the extra, or a desktop user's
    tray quietly stops appearing after an upgrade.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_pyside6_is_not_a_base_dependency() -> None:
    base = _pyproject()["project"]["dependencies"]
    offenders = [d for d in base if "pyside6" in d.lower()]
    assert not offenders, (
        f"PySide6 is back in [project.dependencies]: {offenders}. That is 648 MB of Qt "
        "on every headless install. It belongs in the `desktop` extra."
    )


def test_the_desktop_extra_exists_and_carries_qt() -> None:
    extras = _pyproject()["project"]["optional-dependencies"]
    assert "desktop" in extras, "the `desktop` extra vanished"
    assert any("pyside6" in d.lower() for d in extras["desktop"])


def test_snap_stages_qt_explicitly() -> None:
    """A snap cannot pip-install at runtime, so this omission is unrecoverable."""
    snap = (REPO_ROOT / "snap" / "snapcraft.yaml").read_text(encoding="utf-8")
    staged = [
        line for line in snap.splitlines()
        if line.strip().startswith("- ") and "pyside6" in line.lower()
    ]
    assert staged, (
        "snapcraft.yaml no longer stages PySide6. It used to arrive as a base "
        "dependency; now that it is an extra it must be listed under python-packages, "
        "or the tray and overlay disappear from the snap for good."
    )


def test_documented_install_paths_still_request_the_desktop_extra() -> None:
    """A desktop install must not silently lose its tray."""
    checks = {
        "install.sh": "PySide6",
        "debian/postinst": "yazses[desktop]",
        "scripts/build-deb.sh": "yazses[desktop]",
    }
    missing = [
        path for path, needle in checks.items()
        if needle not in (REPO_ROOT / path).read_text(encoding="utf-8")
    ]
    assert not missing, (
        f"these install paths no longer pull the desktop extra: {missing} -- "
        "a desktop user would install and find no tray icon"
    )


def test_both_desktop_features_can_install_qt_on_demand() -> None:
    """`yazses features enable overlay|tray` has to be able to fetch it."""
    from yazses.system.features import _FEATURE_DEPS

    for slug in ("overlay", "tray"):
        assert slug in _FEATURE_DEPS, f"{slug} cannot install its own dependency"
        probes, packages = _FEATURE_DEPS[slug]
        assert "PySide6" in probes
        assert any("PySide6" in p for p in packages)


def test_importing_the_daemon_does_not_import_qt() -> None:
    """The whole saving is void if something imports Qt eagerly anyway."""
    import subprocess
    import sys

    code = (
        "import sys; import yazses.core.daemon; "
        "print(any(m == 'PySide6' or m.startswith('PySide6.') for m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=180,
        cwd=REPO_ROOT,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False", "importing the daemon pulled in Qt"
