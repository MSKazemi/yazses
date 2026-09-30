"""`yazses setup` on Windows: find what a bare machine lacks and install it.

The frozen installer (`.exe`, winget, Scoop) already bundles Python and every wheel, so
the only thing it cannot carry is the Microsoft Visual C++ runtime that CTranslate2
links against -- a fresh Windows image or a Server SKU often lacks it, and the failure
is a ``DLL load failed`` traceback on the first hold of the hotkey (see
``doctor._stt_engine_check``). A source/pip install can additionally lack the
Windows-only Python packages (``pywin32``, ``pystray``, ``Pillow``); ``pyproject.toml``
pulls them by environment marker, but a partial or ``--no-deps`` install does not.

Pure planner + injected runner, so it is unit-tested on Linux with no Windows host.
Nothing here opens a socket: package downloads are done by ``winget`` / ``pip`` the
user already has, never by YazSes.
"""

from __future__ import annotations

import importlib.util
import platform
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

#: import name -> pip distribution, for the packages `pyproject.toml` pulls on win32.
WINDOWS_PIP_PACKAGES: dict[str, str] = {
    "win32api": "pywin32",
    "pystray": "pystray",
    "PIL": "Pillow",
}

_VCREDIST_ID = {"x64": "Microsoft.VCRedist.2015+.x64", "arm64": "Microsoft.VCRedist.2015+.arm64"}
_VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


@dataclass
class WindowsPlan:
    pip_packages: list[str] = field(default_factory=list)
    vc_redist: bool = False
    arch: str = "x64"
    notes: list[str] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        return not (self.pip_packages or self.vc_redist)


def host_arch() -> str:
    return "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"


def _decoder_loads() -> bool:
    """True when CTranslate2 imports. Only a *load* failure means the VC++ runtime."""
    try:
        import ctranslate2  # type: ignore[import-untyped]  # noqa: F401
    except ModuleNotFoundError:
        return True  # not installed is a pip problem, reported by doctor, not a VC++ one
    except Exception:
        return False
    return True


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def build_windows_plan(
    *,
    find_spec: Callable[[str], object | None] = importlib.util.find_spec,
    decoder_loads: Callable[[], bool] = _decoder_loads,
    frozen: bool | None = None,
    arch: str | None = None,
) -> WindowsPlan:
    frozen = _is_frozen() if frozen is None else frozen
    plan = WindowsPlan(arch=arch or host_arch())
    if not frozen:
        # A frozen build carries its wheels; pip does not exist there and would be wrong.
        for module, dist in WINDOWS_PIP_PACKAGES.items():
            try:
                present = find_spec(module) is not None
            except (ImportError, ValueError):
                present = False
            if not present:
                plan.pip_packages.append(dist)
    if not decoder_loads():
        plan.vc_redist = True
        plan.notes.append(
            "The speech decoder will not load: the Microsoft Visual C++ Redistributable "
            "is missing. Windows will ask for administrator approval once."
        )
    return plan


def apply_windows_plan(
    plan: WindowsPlan,
    *,
    runner: Callable[..., object] = subprocess.run,
    echo: Callable[[str], None] = print,
    which: Callable[[str], str | None] | None = None,
) -> bool:
    """Execute *plan*. Returns True when everything requested succeeded. Never raises."""
    import shutil

    which = which or shutil.which
    if plan.is_noop:
        echo("All Windows requirements already satisfied — nothing to do.")
        return True
    ok = True

    def _run(cmd: list[str]) -> bool:
        try:
            done = runner(cmd, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            echo(f"! could not run {cmd[0]}: {exc}")
            return False
        # 0x8A150061 (as winget's signed exit code) means "already installed" -- success.
        return getattr(done, "returncode", 0) in (0, -1978335135)

    if plan.pip_packages:
        echo(f"Installing Python packages: {' '.join(plan.pip_packages)}")
        if not _run([sys.executable, "-m", "pip", "install", *plan.pip_packages]):
            echo(f"! pip failed — run:  {sys.executable} -m pip install {' '.join(plan.pip_packages)}")
            ok = False
    if plan.vc_redist:
        pkg = _VCREDIST_ID.get(plan.arch, _VCREDIST_ID["x64"])
        if which("winget"):
            echo(f"Installing the Visual C++ Redistributable ({pkg}) with winget…")
            good = _run([
                "winget", "install", "--id", pkg, "-e", "--silent",
                "--accept-package-agreements", "--accept-source-agreements",
            ])
            if not good:
                echo(f"! winget did not finish — install it from {_VCREDIST_URL} and re-run `yazses setup`.")
                ok = False
        else:
            echo(f"! winget not found — install the runtime from {_VCREDIST_URL}, then re-run `yazses setup`.")
            ok = False
    return ok
