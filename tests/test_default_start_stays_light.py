"""A default start does not pay for opt-in features.

The eye and hands-free work added dozens of modules, all behind `enabled = false`. That is only
true if importing the CLI and the daemon -- which every command and every daemon start does --
does not load them. A single module-level `from yazses.gaze.clicks import ...` in
`platform/base.py` made every `yazses` invocation import the whole gaze package, for a type
annotation; nothing failed, it just got slower, which is the kind of regression a functional
test never sees.

The check runs in a fresh interpreter so it sees what a real start sees, not what this pytest
process happens to have loaded.
"""

from __future__ import annotations

import json
import subprocess
import sys

#: Heavy third-party packages that only an opt-in extra may bring in.
HEAVY_THIRD_PARTY = (
    "cv2",
    "mediapipe",
    "PySide6",
    "torch",
    "onnxruntime",
    "faster_whisper",
    "ctranslate2",
)

#: Opt-in feature packages. Their modules must be imported by the code that turns them on,
#: not by the CLI or the daemon module at import time.
OPT_IN_PACKAGES = (
    "yazses.gaze",
    "yazses.perception",
    "yazses.headpointer",
    "yazses.gesture",
    "yazses.handsfree",
    "yazses.eyeeval",
    "yazses.grounding",
    "yazses.settingsui",
    "yazses.endpoint",
    "yazses.prosodypunct",
    "yazses.involuntary",
)

_PROBE = """
import json, sys
import yazses.cli, yazses.core.daemon, yazses.config, yazses.main
print(json.dumps(sorted(sys.modules)))
"""


def _loaded_at_default_start() -> list[str]:
    out = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
        encoding="utf-8",
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def _under(loaded: list[str], package: str) -> list[str]:
    return [m for m in loaded if m == package or m.startswith(package + ".")]


def test_the_probe_sees_the_cli_and_the_daemon() -> None:
    # A probe that loads nothing would make every assertion below vacuously true.
    loaded = _loaded_at_default_start()
    assert "yazses.cli" in loaded and "yazses.core.daemon" in loaded
    assert len(_under(loaded, "yazses")) > 50


def test_no_heavy_third_party_package_is_imported_at_start() -> None:
    loaded = _loaded_at_default_start()
    leaked = {pkg: _under(loaded, pkg)[:3] for pkg in HEAVY_THIRD_PARTY if _under(loaded, pkg)}
    assert not leaked, f"a default start imports optional heavy packages: {leaked}"


def test_no_opt_in_feature_package_is_imported_at_start() -> None:
    loaded = _loaded_at_default_start()
    leaked = {pkg: _under(loaded, pkg)[:3] for pkg in OPT_IN_PACKAGES if _under(loaded, pkg)}
    assert not leaked, (
        f"importing the CLI or the daemon loads opt-in feature code: {leaked}. Import it inside "
        "the function that enables the feature, or under `if TYPE_CHECKING:` if it is only a type."
    )
