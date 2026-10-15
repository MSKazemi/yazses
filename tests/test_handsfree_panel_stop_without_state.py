"""The Pause the window offers before it has read anything is the Pause it offers afterwards (#420).

Pure: no Qt. The window appears at once and reads the daemon on a worker thread, so for the first
moments there is no model to take a button from. ``stop_without_state`` is that button, and these
tests keep it from drifting away from the model's own Pause (a different call, a position, or a
disabled state would each turn the one stop a person came for into something else).
"""
from __future__ import annotations

import pytest

from yazses.handsfree.panel import PanelInputs, build_panel, stop_without_state


def test_it_is_enabled_unconditionally_and_is_a_stop():
    spec = stop_without_state()
    assert spec.enabled is True and spec.why_disabled == ""
    assert spec.kind == "stop" and spec.id == "pause"


def test_it_makes_exactly_the_call_the_models_pause_makes():
    model_pause = build_panel(PanelInputs()).action("pause")
    spec = stop_without_state()
    assert model_pause is not None
    assert spec.ipc == model_pause.ipc
    assert spec.cli == model_pause.cli
    assert spec.label == model_pause.label


def test_it_carries_no_position_and_writes_no_config():
    spec = stop_without_state()
    assert spec.ipc is not None
    assert dict(spec.ipc.params) == {"action": "pause"}
    assert spec.config == ()
    assert spec.needs_restart is False


@pytest.mark.parametrize(
    "reachable",
    [pytest.param(True, id="daemon-reachable"), pytest.param(False, id="daemon-unreachable")],
)
def test_the_models_pause_may_be_disabled_but_the_fallback_never_is(reachable):
    """The model disables Pause when nothing is running; before the first read nothing is known,
    and a stop that is not needed is harmless, so the fallback stays pressable."""
    model_pause = build_panel(PanelInputs(daemon_reachable=reachable)).action("pause")
    assert model_pause is not None and model_pause.enabled is False
    assert stop_without_state().enabled is True
