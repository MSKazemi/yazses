"""Windows openers: ``os.startfile``, the shell's own "open" verb.

:class:`WindowsFileOpener` opens a file with its default app. :class:`WindowsUrlOpener`
hands a custom-scheme URL (``claude://``, ``codex://``) to the program registered for that
scheme. ``os.startfile`` calls ``ShellExecuteW`` inside this process, so YazSes starts no
child with the URL on its command line -- the in-process API ADR-031 §3 names. The program
the shell then starts for a registered scheme receives the URL as its ``%1`` argument,
which other processes of the same user can read while it runs; that half is the client's
registration, not ours. Unverified on a real Windows install with Claude or Codex.

Importable on any OS: ``os.startfile`` exists only on Windows, so it is looked up when a
file or URL is opened, not at import.
"""
from __future__ import annotations

import os

from yazses.platform.base import require_local_scheme


class WindowsFileOpener:
    def open(self, path: str) -> None:
        os.startfile(path)  # type: ignore[attr-defined]  # Windows-only


class WindowsUrlOpener:
    def open_url(self, url: str) -> None:
        require_local_scheme(url)
        try:
            os.startfile(url)  # type: ignore[attr-defined]  # Windows-only
        except OSError as exc:
            # The OSError ShellExecuteW raises names the "file" it was given -- the URL.
            # Re-raise with the errno and reason only, and without the original as context.
            raise OSError(exc.errno, exc.strerror) from None
