"""Install a feature's optional Python dependencies into the running environment.

Some capabilities (e.g. Glance-Type gaze) ride on optional extras that a base
install omits. When the user enables such a feature we install its packages into
the *current* interpreter — whether that is a uv-tool venv, a plain venv, or a
pip environment — so ``yazses features enable <name>`` is turnkey.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence


def missing_modules(modules: Iterable[str]) -> list[str]:
    """Return the import names in *modules* that are not importable."""
    return [m for m in modules if importlib.util.find_spec(m) is None]


def install_command(packages: Sequence[str]) -> list[str]:
    """Return the argv that installs *packages* into the running interpreter.

    Prefers ``uv pip install`` (how yazses is installed on most machines here);
    falls back to ``python -m pip install`` when uv is not on PATH.
    """
    if shutil.which("uv"):
        return ["uv", "pip", "install", "--python", sys.executable, *packages]
    return [sys.executable, "-m", "pip", "install", *packages]


def install_packages(packages: Sequence[str], *, echo=print) -> bool:
    """Install *packages* into the current environment. Returns True on success."""
    if not packages:
        return True
    cmd = install_command(packages)
    echo("Installing dependencies: " + " ".join(packages))
    try:
        subprocess.run(cmd, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        echo(f"Automatic install failed ({exc}). Install manually:\n  {' '.join(cmd)}")
        return False
