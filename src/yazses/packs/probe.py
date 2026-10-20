"""The import probe: mount one pack tree and import its entry modules (ADR-028 §6).

Run as ``yazses packs probe <name> --staged <dir>`` in a **child process** of the same
app, so a native crash kills only the child. The install transaction runs it on the
staged tree before anything is moved into place; CI runs it on the runner for every pack
(the build side's frozen probe).

ADR-028 names four risks only a frozen Windows run can settle (Phase 0): stdlib modules
the base did not collect, missing distribution metadata, base-package submodules
PyInstaller pruned, and a DLL basename collision (``sherpa-onnx-core`` against the
base's ``onnxruntime``). Each must fail **loudly, with a named reason**, so
:func:`classify_failure` turns the exception into one of those kinds, and the child's
exit code carries the kind to the parent.
"""
from __future__ import annotations

import importlib
import sys
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from yazses.packs.manifest import ManifestError, PackManifest, parse_manifest

if TYPE_CHECKING:
    from yazses.platform.base import PackRuntime

__all__ = [
    "EXIT_CODES",
    "PROBE_PREFIX",
    "ProbeResult",
    "classify_failure",
    "describe_exit",
    "run_probe",
]

#: Exit code per failure kind. 0 is success; 2 is Typer's usage error.
EXIT_CODES = {
    "ok": 0,
    "refused": 3,
    "stdlib-gap": 4,
    "missing-metadata": 5,
    "pruned-submodule": 6,
    "native-load": 7,
    "import-error": 8,
    "error": 9,
}
_KINDS = {v: k for k, v in EXIT_CODES.items()}
#: The child's last stdout line starts with this, so the parent can quote it.
PROBE_PREFIX = "YAZSES-PROBE"


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    kind: str
    module: str = ""
    message: str = ""

    @property
    def exit_code(self) -> int:
        return EXIT_CODES.get(self.kind, EXIT_CODES["error"])

    def line(self) -> str:
        return f"{PROBE_PREFIX} {self.kind} {self.module or '-'}: {self.message}"


def classify_failure(
    module: str,
    exc: BaseException,
    *,
    stdlib_names: Collection[str] = frozenset(sys.stdlib_module_names),
    is_present: Callable[[str], bool] = lambda name: name in sys.modules,
) -> tuple[str, str]:
    """``(kind, sentence)`` for an exception raised while importing ``module``."""
    from importlib.metadata import PackageNotFoundError

    if isinstance(exc, PackageNotFoundError):
        dist = exc.args[0] if exc.args else "?"
        return "missing-metadata", (
            f"importing {module} asked for the installed version of {dist!r}, whose "
            "metadata this frozen app does not carry (base metadata gap, ADR-028 Phase 0)"
        )
    if isinstance(exc, ModuleNotFoundError):
        missing = exc.name or ""
        top = missing.split(".", 1)[0]
        if top in stdlib_names:
            return "stdlib-gap", (
                f"importing {module} needs the standard-library module {missing!r}, which "
                "this frozen app did not collect; the pack needs a stdlib/ supplement"
            )
        if "." in missing and is_present(top):
            return "pruned-submodule", (
                f"importing {module} needs {missing!r}, a submodule of the base package "
                f"{top!r} that the frozen app did not collect"
            )
        return "import-error", f"importing {module} needs {missing or 'a module'!r}, which is absent"
    text = str(exc)
    if isinstance(exc, OSError) or "DLL load failed" in text or "WinError" in text:
        return "native-load", (
            f"a native library failed to load while importing {module} ({text}). A DLL "
            "with the same name as one in the base (onnxruntime.dll is the known "
            "candidate) or a missing dependency DLL causes this"
        )
    if isinstance(exc, ImportError):
        return "import-error", f"importing {module} failed: {text}"
    return "error", f"importing {module} raised {exc.__class__.__name__}: {text}"


def describe_exit(code: int, output: str) -> tuple[str, str]:
    """``(kind, sentence)`` from a probe child's exit code and stdout."""
    kind = _KINDS.get(code, "error")
    line = next(
        (ln for ln in reversed(output.splitlines()) if ln.startswith(PROBE_PREFIX)), ""
    )
    if line:
        # "YAZSES-PROBE <kind> <module>: <message>"
        _, _, message = line.partition(": ")
        return kind, message.strip()
    return kind, f"the add-on test exited with code {code} and said nothing"


def run_probe(
    name: str,
    staged: Path,
    *,
    runtime: PackRuntime,
    sys_path: list[str] | None = None,
    import_module: Callable[[str], object] = importlib.import_module,
    handles: list[object] | None = None,
) -> ProbeResult:
    """Mount ``staged`` (appended, like the real mount: ``site/``, then ``path_entries``,
    then ``stdlib/``) and import every entry module. Never raises.

    Unlike the startup mount, the probe does **not** refuse an elevated process. The
    elevation rule exists so that a user-writable tree is never loaded *automatically*
    into an administrator process; the probe loads only the directory it was explicitly
    given, and the install transaction only ever starts it from the user's unelevated
    process (installing refuses elevated). The release build runs it on the Windows CI
    runner, whose account is an administrator; refusing there would withhold every pack.
    """
    path_list = sys.path if sys_path is None else sys_path
    keep: list[object] = [] if handles is None else handles
    try:
        try:
            manifest: PackManifest = parse_manifest(
                (staged / "pack.json").read_text(encoding="utf-8")
            )
        except (OSError, ManifestError) as exc:
            return ProbeResult(False, "refused", message=f"pack.json: {exc}")
        if manifest.name != name:
            return ProbeResult(False, "refused", message=(
                f"the tree is the {manifest.name!r} pack, not {name!r}"
            ))
        for native in manifest.native_dirs:
            try:
                keep.append(runtime.add_native_dir(staged / Path(*native.split("/"))))
            except Exception as exc:  # noqa: BLE001
                return ProbeResult(False, "native-load", message=(
                    f"could not add the native library folder {native} ({exc})"
                ))
        extra = [Path(*p.split("/")) for p in manifest.path_entries]
        for rel in (Path("site"), *extra, Path("stdlib")):
            p = staged / rel
            if p.is_dir() and str(p) not in path_list:
                path_list.append(str(p))
        importlib.invalidate_caches()
        for module in manifest.entry_modules:
            try:
                import_module(module)
            except BaseException as exc:  # noqa: BLE001 - classify, never crash
                if isinstance(exc, KeyboardInterrupt):
                    raise
                kind, message = classify_failure(module, exc)
                return ProbeResult(False, kind, module, message)
        return ProbeResult(True, "ok", message=(
            f"imported {', '.join(manifest.entry_modules)}"
        ))
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(False, "error", message=f"{exc.__class__.__name__}: {exc}")
