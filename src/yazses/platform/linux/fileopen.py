"""Linux openers: ``xdg-open``. The BSDs use them too (``xdg-utils`` is in ports and pkgsrc).

:class:`LinuxFileOpener` opens a file with the default app. :class:`LinuxUrlOpener` hands a
custom-scheme URL (``claude://``, ``codex://``) to the program registered for it -- the
``UrlOpener`` seam ADR-031 §3 asks for.

**The local exposure, stated rather than hidden.** ``xdg-open`` takes the URL as a
command-line argument, and "send to" puts the user's dictation in that URL. While
``xdg-open`` runs, the text is in ``/proc/<pid>/cmdline``: readable by every process of
the same user, and -- unless ``/proc`` is mounted with ``hidepid=`` -- by every local
user. The client the desktop starts usually receives the URL as an argument too (the
``%u`` in its ``.desktop`` file), so if the hand-off *starts* the client, the text stays
in that process's argument list for as long as it runs. A D-Bus hand-off through the
desktop portal's ``OpenURI`` would avoid the first half; it is not built, and the second
half is the client's, not ours.
"""
from __future__ import annotations

import subprocess
import threading

from yazses.platform.base import require_local_scheme

#: How long to wait for ``xdg-open`` to say whether it handed the URL off. It normally
#: exits within a second, with 0 or a failure status (4 when no program is registered
#: for the scheme). Some desktops' fallbacks run the handler in the foreground instead,
#: so a still-running ``xdg-open`` at this point counts as handed off and is left alone:
#: killing it could kill the client it is starting.
XDG_OPEN_WAIT_S = 5.0


class LinuxFileOpener:
    def open(self, path: str) -> None:
        subprocess.run(["xdg-open", path], check=True)


class LinuxUrlOpener:
    def open_url(self, url: str) -> None:
        require_local_scheme(url)
        # One argv element, no shell. stdout/stderr discarded: xdg-open quotes its
        # argument in its error messages, and the daemon's stderr is its log.
        proc = subprocess.Popen(
            ["xdg-open", url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        try:
            status = proc.wait(timeout=XDG_OPEN_WAIT_S)
        except subprocess.TimeoutExpired:
            # Still running: handed to a handler that has not returned yet. Reap it in
            # the background so it does not linger as a zombie.
            threading.Thread(target=proc.wait, name="xdg-open-reaper", daemon=True).start()
            return
        if status != 0:
            # The status only -- a CalledProcessError would carry the argv, i.e. the URL.
            raise OSError(f"xdg-open exited with status {status}")
