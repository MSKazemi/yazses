"""`mic-level --set` must name the one restart command that is true on every install.

It printed ``yazses stop && yazses start``. A running daemon ignores a changed threshold until it
is restarted (the same module's own drift note says "Fix: yazses restart"), and `yazses restart`
is the command that handles a systemd user unit as well as a plain process, so the docs and the
printed advice must agree on it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import yazses.cli as cli
import yazses.system.miclevel as miclevel


def test_set_prints_yazses_restart(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    config = tmp_path / "config.toml"
    fake = SimpleNamespace(paths=SimpleNamespace(config_file=config))
    monkeypatch.setattr(cli, "get_platform", lambda: fake)
    monkeypatch.setattr(cli, "_live_vad_threshold", lambda _platform: None)
    rng = np.random.default_rng(0)
    clips = iter([
        (rng.standard_normal(16000 * 2) * 0.004).astype("float32"),  # the room
        (rng.standard_normal(16000 * 4) * 0.08).astype("float32"),   # the voice
    ])
    monkeypatch.setattr(miclevel, "record", lambda *a, **k: next(clips))

    assert cli._calibrate_mic(seconds=4.0, set_threshold=True) is True
    out = capsys.readouterr().out
    assert "Restart to pick it up:  yazses restart" in out
    assert "yazses stop && yazses start" not in out
    assert "vad_threshold" in config.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "page", ["get-started.md", "install-linux.md", "how-to/silent-audio-discarding.md"]
)
def test_the_docs_name_the_same_command_near_the_calibration(page: str) -> None:
    """Every page that tells a running install to re-run `mic-level --set` says `yazses restart`
    close by, and none still sends the reader to a different command for it."""
    text = (Path(__file__).resolve().parents[1] / "docs" / page).read_text(encoding="utf-8")
    spots = [i for i in range(len(text)) if text.startswith("mic-level --set", i)]
    assert spots, page
    assert any("yazses restart" in text[i : i + 400] for i in spots), page
    assert "systemctl --user restart yazses.service" not in text.split("mic-level --set")[1][:400]
