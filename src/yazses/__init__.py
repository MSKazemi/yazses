"""YazSes — offline, on-device voice dictation.

``__version__`` is read from the installed package metadata rather than written here.
It used to be a hardcoded string, and it drifted: it still said ``2.10.0.dev5`` while
`yazses --version` — which has always read the metadata — reported 2.12.1. Anything
trusting the constant, including the diagnostic report, was quietly reporting a version
that had not existed for several releases, which is worse than no version at all when the
point is to work out what someone is running.

Resolved lazily (PEP 562). Reading it eagerly cost ~52 ms on every single
invocation — `importlib.metadata` walks `sys.path` hunting for a ``.dist-info``,
and it was the most expensive import in the tree — while `status`, `stop` and the
shell completion that runs on each Tab never look at the version at all. Deferring
changes only *when* the metadata is read, never *what* it says.
"""

__all__ = ["__version__"]


def __getattr__(name: str) -> str:
    """Resolve `__version__` on first access, then cache it in the module dict.

    Rebinding into `globals()` means the metadata walk happens at most once per
    process: `__getattr__` is consulted only for names the module does not already
    have, so the second read is an ordinary attribute lookup.
    """
    if name != "__version__":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    try:
        value = _pkg_version("yazses")
    except PackageNotFoundError:  # a source tree with nothing installed
        value = "0.0.0+unknown"
    globals()["__version__"] = value
    return value


def __dir__() -> list[str]:
    """`dir()` does not consult `__getattr__`, so say it explicitly — otherwise
    `__version__` vanishes from introspection and from tab-completion."""
    return sorted([*globals(), "__version__"])
