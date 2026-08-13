"""Honest availability reporting for lazily-imported, pluggable backends.

Several capabilities dispatch on a ``backend = ...`` config key and import the chosen
adapter lazily, so a base install stays light and nothing heavy loads until a feature
is explicitly enabled (ADR-011). Every one of those factories has to answer the same
question when that import fails — *why*, and *what can the user do about it?* — and
there are two very different answers:

* the third-party dependency is not installed → installing the named extra fixes it;
* the adapter itself was never shipped in this build → installing anything is futile,
  and telling the user to try sends them after a fix that cannot work.

The factories used to collapse both cases into "install the ``X`` extra".
:func:`probe_backend` tells them apart and produces an accurate message; callers log
it and degrade exactly as before.

Both answers are live in this build, and the distinction is not hypothetical:

* ``resemblyzer`` and ``pyannote`` **do** ship adapters now, each behind its own
  extra (``voiceprint-resemblyzer``, ``diarization-pyannote``). Neither may point at
  the extra it sits beside — ``voiceprint`` is speechbrain and ``diarization`` is
  sherpa-onnx, so naming those would send the user after a package that cannot
  supply the backend they selected.
* ``deepfilternet`` has no adapter and **cannot get one**: every release of it caps
  ``numpy<2.0`` while this project requires ``numpy>=2.4.6``, so the two are
  unresolvable in one environment on any Python version. There is deliberately no
  ``denoise`` extra, because an extra that can never install is a worse lie than an
  honest "not implemented in this build". See issue #69.

The probe is pure apart from the injected module lookup, so it unit-tests without any
optional dependency installed.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from yazses.system.deps import missing_modules


@dataclass(frozen=True)
class BackendStatus:
    """Why a pluggable backend can or cannot run, and what (if anything) fixes it."""

    backend: str
    available: bool
    reason: str = ""
    remedy: str = ""
    missing: tuple[str, ...] = field(default_factory=tuple)

    @property
    def implemented(self) -> bool:
        """True when the adapter ships in this build (deps may still be absent)."""
        return self.available or bool(self.remedy)

    @property
    def message(self) -> str:
        """One-line human-readable explanation, remedy included when one exists."""
        if self.available:
            return f"backend {self.backend!r} is available"
        return f"{self.reason}; {self.remedy}" if self.remedy else self.reason


def probe_backend(
    backend: str,
    *,
    adapter: str,
    requires: Iterable[str] = (),
    extra: str | None = None,
    missing: Callable[[Iterable[str]], Sequence[str]] = missing_modules,
) -> BackendStatus:
    """Report whether *backend* can actually run, and how to fix it if not.

    ``adapter`` is the in-tree dotted module implementing the backend, ``requires``
    the third-party import names it needs, and ``extra`` the pip extra that provides
    them. ``missing`` is injected for testing.

    A missing *adapter* outranks missing dependencies: when the adapter was never
    shipped, no amount of installing helps, so no remedy is offered.
    """
    if missing([adapter]):
        return BackendStatus(
            backend=backend,
            available=False,
            reason=(
                f"the {backend!r} backend is not implemented in this build "
                f"(no {adapter})"
            ),
            remedy="",
            missing=(adapter,),
        )

    absent = tuple(missing(tuple(requires)))
    if absent:
        need = ", ".join(absent)
        return BackendStatus(
            backend=backend,
            available=False,
            reason=f"the {backend!r} backend needs {need}",
            remedy=(
                f"install the `{extra}` extra"
                if extra
                else f"install: {' '.join(absent)}"
            ),
            missing=absent,
        )

    return BackendStatus(backend=backend, available=True)
