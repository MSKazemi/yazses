import subprocess

from yazses.inject.payload import hide_payload


class WtypeInjector:
    def inject(self, text: str) -> None:
        with hide_payload():
            subprocess.run(["wtype", "--", text], check=True, timeout=10)

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        args: list[str] = []
        for _ in range(count):
            args += ["-k", "BackSpace"]
        subprocess.run(["wtype"] + args, check=True, timeout=10)

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        # wtype uses -k for key names, with modifiers via -M/-m syntax.
        # For shift+Left style: split on "+" and build modifier flags.
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
