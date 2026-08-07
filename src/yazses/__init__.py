"""YazSes — offline, on-device voice dictation.

``__version__`` is read from the installed package metadata rather than written here.
It used to be a hardcoded string, and it drifted: it still said ``2.10.0.dev5`` while
`yazses --version` — which has always read the metadata — reported 2.12.1. Anything
trusting the constant, including the diagnostic report, was quietly reporting a version
that had not existed for several releases, which is worse than no version at all when the
point is to work out what someone is running.
"""
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("yazses")
except PackageNotFoundError:  # running from a source tree with nothing installed
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
