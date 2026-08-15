"""`windowctl` must not advertise verbs nothing can carry out.

For a long time the feature described itself as *"Hands-free desktop layout:
'move window left half', 'maximize', 'workspace 3'"* — and every one of those
three examples was dead. Their grammar is `windowctl/commands.py::parse_wm_command`,
which nothing in `src/` imports, and the `WindowBackend` protocol
(`windowctl/focus.py`) declares only `list_windows()` and `focus()`. There is no
method that could execute a `WmAction` even after someone wired the parser up.

So `yazses features enable windowctl` succeeded, `yazses features` listed it as
available, and the three things it named did nothing. That is worse than not
shipping the feature: a toggle that reports success teaches people the product is
broken in some way they cannot see.

The registry now describes focusing only, which is what runs. This pins that pair
together: **the description may name a layout verb only when the backend has grown
a method that performs it.** Restoring the promise then means restoring the
capability, in the same change.
"""
from __future__ import annotations

import re

from yazses.config import Config
from yazses.system.features import grouped_features
from yazses.windowctl.focus import WindowBackend

#: Words that promise moving, sizing or workspace-switching — none of which the
#: backend protocol can do. Focusing and raising are fine: those work.
LAYOUT_VERBS = ("move window", "maximize", "maximise", "workspace", "tile", "snap to")

#: What a backend method would plausibly be called if someone implemented it.
LAYOUT_METHODS = ("move", "resize", "maximize", "maximise", "tile", "workspace", "set_geometry")


def _windowctl_entry():
    for _category, _blurb, feats in grouped_features(Config()):
        for feat in feats:
            if feat.slug == "windowctl":
                return feat
    raise AssertionError("the windowctl feature is no longer in the registry")


def _backend_methods() -> set[str]:
    return {name for name in dir(WindowBackend) if not name.startswith("_")}


def test_the_feature_exists_and_this_guard_is_looking_at_it() -> None:
    """Guard the guard: a renamed slug would make every assertion below vacuous."""
    feat = _windowctl_entry()
    assert feat.name and feat.why


def test_no_layout_verb_is_promised_without_a_backend_that_can_do_it() -> None:
    feat = _windowctl_entry()
    text = f"{feat.name} {feat.why}".lower()
    promised = [verb for verb in LAYOUT_VERBS if verb in text]
    if not promised:
        return

    methods = _backend_methods()
    capable = [m for m in LAYOUT_METHODS if m in methods]
    assert capable, (
        f"windowctl advertises {promised} but WindowBackend only offers "
        f"{sorted(methods)} — there is no method that could carry any of them out, "
        f"so enabling the feature would succeed and the examples would do nothing. "
        f"Either add the backend capability, or stop promising it."
    )


def test_the_description_still_promises_what_does_work() -> None:
    """The opposite failure: trimming it until it describes nothing. Focusing by
    name is wired (core/daemon.py imports parse_focus_command) and should be said."""
    feat = _windowctl_entry()
    text = f"{feat.name} {feat.why}".lower()
    assert "focus" in text or "switch to" in text


def test_the_wayland_limitation_is_stated() -> None:
    """The backend is X11-only; a Wayland user enabling this needs to know before
    they conclude the product is broken."""
    feat = _windowctl_entry()
    assert re.search(r"x11|wayland", f"{feat.name} {feat.why}", re.I)


def test_the_layout_grammar_is_still_present_for_whoever_wires_it() -> None:
    """The parser is good code with tests; this is a wiring gap, not a deletion.
    If someone removes it, that should be a deliberate choice rather than a
    side effect of tidying up after this guard."""
    from yazses.windowctl.commands import parse_wm_command

    assert parse_wm_command("move window left half") is not None
