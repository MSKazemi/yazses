"""A default install never loads the biosignal package or a device library.

`tests/test_biosignal_daemon_wiring.py` spies on the imports of one build call, in a process
where the test module has already imported other things. This runs a fresh interpreter, so it
sees everything the import chain pulls in: the CLI and the daemon module themselves, and the
daemon's activation sources built from a default config. If any of them starts importing the
package at module level, every dictation user pays for a feature they did not turn on.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap

DEVICE_LIBRARIES = ("pylsl", "pyxdf", "brainflow", "bleak", "serial")

PROBE = textwrap.dedent(
    """
    import json
    import sys

    import yazses.cli
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    config = Config()
    daemon = Daemon(config=config, platform=get_platform())
    sources = daemon._build_activation_sources(config)
    print(json.dumps({
        "enabled": config.biosignal.enabled,
        "sources": len(sources),
        "biosignal_handle": daemon._biosignal is None and daemon._biosignal_runner is None,
        "loaded": sorted(m for m in sys.modules if m == "yazses.biosignal"
                         or m.startswith("yazses.biosignal.")),
        "libraries": sorted(set(sys.modules) & set(%r)),
    }))
    """
) % (DEVICE_LIBRARIES,)


def test_a_default_daemon_loads_no_biosignal_code_in_a_fresh_process():
    result = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["enabled"] is False
    assert report["sources"] == 0
    assert report["biosignal_handle"] is True
    assert report["loaded"] == []
    assert report["libraries"] == []
