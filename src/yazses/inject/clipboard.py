import os
import shutil
import subprocess
import time

from yazses.inject.ydotool import run_ydotool_keys

# Milliseconds to wait after wl-copy sets the clipboard before sending Ctrl+V, so
# the new Wayland selection has propagated to the compositor. Without it the
# immediate paste occasionally fires before the selection is live and nothing is
# pasted — the text sits on the clipboard but is never typed (intermittent).
_CLIPBOARD_SETTLE_S = 0.15


def _ydotool_ready() -> bool:
    """ydotool only works with a running ydotoold (its socket must exist).

    Socket discovery is `inject.auto`'s, imported inside the function because
    `auto` reaches this module through the registry. Its own copy of the search
    looked only in ``$XDG_RUNTIME_DIR`` and so answered "no ydotool" on Debian and
    Ubuntu, where ydotoold is 0.1.8 and binds ``/tmp/.ydotool_socket`` -- the very
    machines where the clipboard path is the fallback that has to work.
    """
    if not shutil.which("ydotool"):
        return False
    from yazses.inject.auto import find_ydotool_socket

    return find_ydotool_socket() is not None


def _paste_wayland() -> None:
    """Send Ctrl+V on Wayland with whichever tool this session has."""
    if _ydotool_ready():
        # A 40 ms key delay spaces the events out so the compositor reliably sees
        # Ctrl held when V is pressed (back-to-back events are occasionally missed).
        run_ydotool_keys(["ctrl+v"], timeout=5, key_delay_ms=40)
        return
    if shutil.which("wtype"):
        subprocess.run(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"], check=True, timeout=5)
        return
    raise RuntimeError("No tool available to send Ctrl+V on Wayland (install ydotool, or wtype on wlroots)")


class ClipboardInjector:
    def inject(self, text: str) -> None:
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        if is_wayland:
            subprocess.run(["wl-copy", "--", text], check=True, timeout=5)
            time.sleep(_CLIPBOARD_SETTLE_S)
            _paste_wayland()
        else:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode(),
                check=True,
                timeout=5,
            )
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                check=True,
                timeout=5,
            )

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        if is_wayland:
            if _ydotool_ready():
                run_ydotool_keys(["KEY_BACKSPACE"] * count, timeout=10)
            elif shutil.which("wtype"):
                args = []
                for _ in range(count):
                    args += ["-k", "BackSpace"]
                subprocess.run(["wtype"] + args, check=True, timeout=10)
            else:
                raise RuntimeError("No tool available to send BackSpace on Wayland (install ydotool or wtype)")
        else:
            subprocess.run(
                ["xdotool", "key", "--repeat", str(count), "BackSpace"],
                check=True,
                timeout=10,
            )

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        if is_wayland:
            if _ydotool_ready():
                run_ydotool_keys(keys, timeout=10)
            elif shutil.which("wtype"):
                args: list[str] = []
                for key in keys:
                    parts = key.split("+")
                    modifiers = parts[:-1]
                    key_name = parts[-1]
                    for mod in modifiers:
                        args += ["-M", mod]
                    args += ["-k", key_name]
                    for mod in modifiers:
                        args += ["-m", mod]
                subprocess.run(["wtype"] + args, check=True, timeout=10)
            else:
                raise RuntimeError("No tool available to send key sequence on Wayland (install ydotool or wtype)")
        else:
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers"] + keys,
                check=True,
                timeout=10,
            )
