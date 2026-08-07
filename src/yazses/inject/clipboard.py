import os
import shutil
import subprocess
import time

from yazses.inject.ydotool import ydotool_key_args

# Milliseconds to wait after wl-copy sets the clipboard before sending Ctrl+V, so
# the new Wayland selection has propagated to the compositor. Without it the
# immediate paste occasionally fires before the selection is live and nothing is
# pasted — the text sits on the clipboard but is never typed (intermittent).
_CLIPBOARD_SETTLE_S = 0.15


def _ydotool_ready() -> bool:
    """ydotool only works with a running ydotoold (its socket must exist).

    Mirrors inject.auto.ydotool_ready (kept local to avoid a circular import).
    """
    if not shutil.which("ydotool"):
        return False
    sock = os.environ.get("YDOTOOL_SOCKET")
    if not sock:
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if not runtime:
            uid = os.getuid() if hasattr(os, "getuid") else 0
            runtime = f"/run/user/{uid}"
        sock = os.path.join(runtime, ".ydotool_socket")
    return os.path.exists(sock)


def _paste_cmd_wayland() -> list[str]:
    if _ydotool_ready():
        # ydotool's `key` ignores symbolic names — use numeric keycodes. `-d 40`
        # spaces the events out so the compositor reliably sees Ctrl held when V
        # is pressed (back-to-back events are occasionally missed).
        return ["ydotool", "key", "-d", "40"] + ydotool_key_args("ctrl+v")
    if shutil.which("wtype"):
        return ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"]
    raise RuntimeError("No tool available to send Ctrl+V on Wayland (install ydotool, or wtype on wlroots)")


class ClipboardInjector:
    def inject(self, text: str) -> None:
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        if is_wayland:
            subprocess.run(["wl-copy", "--", text], check=True, timeout=5)
            time.sleep(_CLIPBOARD_SETTLE_S)
            subprocess.run(_paste_cmd_wayland(), check=True, timeout=5)
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
                subprocess.run(["ydotool", "key"] + ydotool_key_args("KEY_BACKSPACE") * count, check=True, timeout=10)
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
                args: list[str] = []
                for combo in keys:
                    args += ydotool_key_args(combo)
                subprocess.run(["ydotool", "key"] + args, check=True, timeout=10)
            elif shutil.which("wtype"):
                args = []
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
