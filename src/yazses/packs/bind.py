"""Bind a pack's native code to the base's own copy of a shared DLL (ADR-028 §1, M1).

**Why.** ``sherpa-onnx-core``'s Windows wheel ships its own ``onnxruntime.dll`` (an
unsigned 1.28.2 build) while the frozen base ships Microsoft's signed 1.28.0. Two files
with one module name cannot coexist safely in one process, so the build drops the pack's
copy and records the name in ``pack.json``'s ``bind_to_base``. The runtime must then make
the pack's extension use the **base's** copy, deterministically.

**How.** Windows answers a DLL request by module name from the loaded-module list first,
"no matter which folder it was loaded from"
(`DLL search order <https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order>`_).
So the base's copy is loaded **by absolute path from the frozen app's own folder** before
any of the pack's modules is imported; the pack's extension then resolves the name to it.
The loader is never asked to *search* for the name, so a copy elsewhere on the search
path can never be the one that answers. Afterwards every loaded module of that name is
listed: it must be exactly the base's file, or the pack is refused.

**When.** Lazily. :func:`yazses.packs.mount.apply` installs a :class:`FirstUseBinder` on
``sys.meta_path`` for each mounted pack that lists ``bind_to_base``; the binding runs the
first time one of that pack's top-level modules is imported, and the finder then removes
itself. Nothing is loaded at start-up, and a process that never uses the pack never loads
the base's DLL for it. The import probe (``yazses packs probe``) binds eagerly, because it
is the first use.

**Refusal** carries a named reason (:class:`Binding.reason`): the DLL is missing from the
base, the base carries more than one file of that name, it does not load, its version is
below ``bind_min_versions``, the version cannot be read while a minimum is required, or
another file of that name is already loaded. There is no fallback to any other copy.

The decisions (:func:`choose_base_copy`, :func:`judge_version`, :func:`judge_loaded`,
:func:`top_level_names`, :func:`version_at_least`) are pure. :func:`bind_pack` touches the
OS only through the injected :class:`~yazses.platform.base.PackRuntime`.
"""
from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from yazses.packs.manifest import PackManifest
    from yazses.platform.base import PackRuntime

__all__ = [
    "BINDINGS",
    "BindMode",
    "BindRequest",
    "Binding",
    "FirstUseBinder",
    "OutOfProcessHost",
    "bind_mode",
    "bind_pack",
    "choose_base_copy",
    "describe_bindings",
    "judge_loaded",
    "judge_version",
    "parse_version",
    "requests_for",
    "top_level_names",
    "version_at_least",
]

#: What each pack bound to in this process, by pack name (for ``packs`` status output).
BINDINGS: dict[str, tuple[Binding, ...]] = {}


# ---- the requests ------------------------------------------------------------------

@dataclass(frozen=True)
class BindRequest:
    dll: str
    minimum: str | None = None


def requests_for(manifest: PackManifest) -> tuple[BindRequest, ...]:
    """One request per ``bind_to_base`` name, with its minimum version if stated."""
    mins = {d.casefold(): v for d, v in manifest.bind_min_versions}
    return tuple(BindRequest(d, mins.get(d.casefold())) for d in manifest.bind_to_base)


# ---- the out-of-process seam (ADR-028 §1), deliberately not built ------------------

BindMode = Literal["in-process", "out-of-process"]


class OutOfProcessHost(Protocol):
    """The ADR-028 §1 fallback: run a pack's feature in a child process that has only
    the pack's own DLLs loaded, and talk to it over IPC. **Not implemented.**

    TODO(ADR-028 §1, M1): build this only if the Phase 0 spike
    (``.github/workflows/packs-spike.yml``, check (d), ``loaded_collisions`` /
    ``loaded_onnxruntime`` in the result JSON) shows that ``sherpa_onnx`` with its own
    ``onnxruntime.dll`` dropped either fails to import against the base's 1.28.0
    (``DLL load failed`` / a missing ORT entry point) or ends up with any
    ``onnxruntime.dll`` loaded from a path other than the base's. Then switch
    :func:`bind_mode` for that pack and give this Protocol a backend.
    """

    def start(self, pack: str, entry_module: str) -> object:
        """Start the child for ``pack`` and return a handle the feature can call."""
        ...


def bind_mode(manifest: PackManifest) -> BindMode:
    """How ``manifest``'s ``bind_to_base`` DLLs are honoured. Always ``"in-process"``
    today: see :class:`OutOfProcessHost` for what would change that."""
    return "in-process"


# ---- pure decisions ----------------------------------------------------------------

_VERSION_PREFIX = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """The leading dotted-number part of ``text`` (``"1.28.0-dev"`` -> ``(1, 28, 0)``),
    or ``None`` when there is none."""
    if not text:
        return None
    m = _VERSION_PREFIX.match(text)
    if m is None:
        return None
    return tuple(int(p) for p in m.group(1).split("."))


def version_at_least(have: str | None, minimum: str) -> bool | None:
    """``True``/``False``, or ``None`` when either side cannot be read. Missing trailing
    parts count as zero, so ``1.28`` equals ``1.28.0``."""
    a, b = parse_version(have), parse_version(minimum)
    if a is None or b is None:
        return None
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) >= b + (0,) * (width - len(b))


def _key(path: Path | str) -> str:
    """Comparison key for a module path: Windows reports some with a ``\\\\?\\`` prefix
    and in any letter case."""
    text = str(path)
    if text.startswith("\\\\?\\"):
        text = text[4:]
    return os.path.normcase(os.path.normpath(text))


def choose_base_copy(dll: str, candidates: Sequence[Path]) -> tuple[Path | None, str]:
    """``(path, "")`` when the base carries exactly one ``dll``, else ``(None, reason)``.
    Two copies are refused rather than ranked: a guess is not deterministic."""
    unique = sorted({_key(p): p for p in candidates}.values(), key=str)
    if not unique:
        return None, (
            f"this copy of YazSes does not contain {dll}, which the add-on must share "
            "with it; reinstall YazSes (the add-on never uses another copy of that file)"
        )
    if len(unique) > 1:
        return None, (
            f"this copy of YazSes contains {len(unique)} files named {dll} "
            f"({', '.join(str(p) for p in unique)}), and the add-on will not guess which "
            "one to share"
        )
    return unique[0], ""


def judge_version(dll: str, version: str | None, minimum: str | None) -> str:
    """``""`` when ``version`` satisfies ``minimum`` (or no minimum is stated)."""
    if minimum is None:
        return ""
    ok = version_at_least(version, minimum)
    if ok is None:
        return (
            f"the version of YazSes's own {dll} could not be read ({version or 'none'}), "
            f"and the add-on needs {minimum} or newer"
        )
    if not ok:
        return (
            f"YazSes's own {dll} is version {version}; the add-on needs {minimum} or "
            "newer. Update YazSes"
        )
    return ""


def judge_loaded(dll: str, expected: Path, loaded: Sequence[Path] | None) -> str:
    """``""`` when every loaded module named ``dll`` is ``expected``, and it is loaded."""
    if loaded is None:
        return f"could not list the loaded libraries to confirm which {dll} is in use"
    want = _key(expected)
    others = sorted({str(p) for p in loaded if _key(p) != want})
    if others:
        return (
            f"another {dll} is loaded from {', '.join(others)}, so the add-on would not "
            f"be guaranteed to use YazSes's own copy ({expected})"
        )
    if not any(_key(p) == want for p in loaded):
        return f"YazSes's own {dll} ({expected}) is not loaded after loading it"
    return ""


_NOT_MODULES = (".dist-info", ".data", ".egg-info")


def top_level_names(entries: Iterable[tuple[str, bool]]) -> frozenset[str]:
    """Top-level importable names from a directory listing of ``(name, is_dir)``:
    packages, ``.py`` modules and extension modules (``foo.cp312-win_amd64.pyd``)."""
    out: set[str] = set()
    for name, is_dir in entries:
        if is_dir:
            if name != "__pycache__" and not name.endswith(_NOT_MODULES) and name.isidentifier():
                out.add(name)
            continue
        stem, dot, ext = name.partition(".")
        if dot and stem.isidentifier() and name.rsplit(".", 1)[-1] in {"py", "pyc", "pyd", "so"}:
            out.add(stem)
    return frozenset(out)


@dataclass(frozen=True)
class Binding:
    """What one ``bind_to_base`` DLL of one pack bound to. ``reason`` empty means bound."""

    pack: str
    dll: str
    path: Path | None = None
    version: str | None = None
    minimum: str | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.reason

    def describe(self) -> str:
        """One line, no newline: what bound, or why not."""
        if not self.ok:
            return f"{self.dll}: refused ({self.reason})"
        floor = f", needs {self.minimum}+" if self.minimum else ""
        return (f"{self.dll} -> {self.path} (version {self.version or 'unknown'}{floor}), "
                "YazSes's own copy")


def describe_bindings(bindings: Iterable[Binding]) -> str:
    return "; ".join(b.describe() for b in bindings)


# ---- the binding, through the injected runtime --------------------------------------

def bind_pack(
    pack: str,
    requests: Sequence[BindRequest],
    runtime: PackRuntime,
    *,
    keep: list[object] | None = None,
) -> tuple[Binding, ...]:
    """Load the base's copy of every requested DLL by absolute path, check its version
    and that nothing else of that name is loaded. Stops at the first refusal. Never
    raises. The loaded libraries' handles go into ``keep``."""
    out: list[Binding] = []
    for req in requests:
        try:
            path, why = choose_base_copy(req.dll, runtime.base_native_candidates(req.dll))
            if path is None:
                out.append(Binding(pack, req.dll, minimum=req.minimum, reason=why))
                break
            try:
                handle, version = runtime.load_base_native(path)
            except OSError as exc:
                out.append(Binding(pack, req.dll, path, minimum=req.minimum, reason=(
                    f"YazSes's own {req.dll} ({path}) could not be loaded ({exc})"
                )))
                break
            if keep is not None:
                keep.append(handle)
            why = judge_version(req.dll, version, req.minimum) or judge_loaded(
                req.dll, path, runtime.loaded_native_paths(req.dll)
            )
            out.append(Binding(pack, req.dll, path, version, req.minimum, why))
            if why:
                break
        except Exception as exc:  # noqa: BLE001 - a refusal, never a crash
            out.append(Binding(pack, req.dll, minimum=req.minimum, reason=(
                f"binding {req.dll} failed ({exc.__class__.__name__}: {exc})"
            )))
            break
    return tuple(out)


class FirstUseBinder:
    """A ``sys.meta_path`` finder that binds one pack the first time any of its
    top-level modules is imported, then gets out of the way.

    It never finds a module itself (``find_spec`` returns ``None``, so the normal path
    finder imports the pack). On a refusal it raises :class:`ImportError` naming the
    reason for **every** import of the pack's modules, so the pack's native code is
    never loaded against anything but the base's DLL.
    """

    def __init__(
        self,
        pack: str,
        requests: Sequence[BindRequest],
        triggers: Iterable[str],
        runtime: PackRuntime,
        *,
        meta_path: list[Any],
        keep: list[object],
        on_refused: Callable[[str, str], None] | None = None,
    ) -> None:
        self.pack = pack
        self.requests = tuple(requests)
        self.triggers = frozenset(triggers)
        self._runtime = runtime
        self._meta_path = meta_path
        self._keep = keep
        self._on_refused = on_refused
        self._lock = threading.RLock()
        self.result: tuple[Binding, ...] | None = None

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if fullname.partition(".")[0] not in self.triggers:
            return None
        with self._lock:
            if self.result is None:
                self.result = bind_pack(self.pack, self.requests, self._runtime,
                                        keep=self._keep)
                BINDINGS[self.pack] = self.result
                refused = [b for b in self.result if not b.ok]
                if not refused:
                    try:
                        self._meta_path.remove(self)
                    except ValueError:
                        pass
                elif self._on_refused is not None:
                    self._on_refused(self.pack, refused[0].reason)
        refused = [b for b in self.result if not b.ok]
        if refused:
            raise ImportError(
                f"YazSes refused the {self.pack!r} add-on: {refused[0].reason}",
                name=fullname,
            )
        return None

    def invalidate_caches(self) -> None:
        return None
