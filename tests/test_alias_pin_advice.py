"""`yazses audio status` told you to pin a name that cannot be pinned.

On this machine, `audio status` resolves the OS default's routing alias through wpctl and
prints:

    OS default:    default
                   → Raptor Lake-P/U/H cAVS Digital Microphone  (volume 65%)
                   ⚠ that is a routing alias, not a microphone ...
                     Pin a real one to be sure:
                     yazses audio use <name>   (see `yazses audio devices`)

Printed directly under the resolved device name, that reads as "type that name". It does
not work:

    resolve_input_device("Raptor Lake-P/U/H cAVS Digital Microphone", devices) -> None

The friendly name comes from the sound server's graph. `audio use` matches against
PortAudio's capture list, which on this machine offers only `sof-hda-dsp: - (hw:0,0)`,
`sof-hda-dsp: - (hw:0,6)`, `sof-hda-dsp: - (hw:0,7)`, `sysdefault`, `pipewire` and
`default` — no entry names a microphone, and four of the six are routes.

## Why the outcome is silent rather than an error

`audio use` warns on a name it cannot match and then **pins it anyway**, deliberately, so a
device can be pinned before it is plugged in. On its own that is right. Combined with
advice to type an unmatchable name it is the worst case: the pin is accepted, never
resolves, capture quietly falls back to the alias, and the user believes they have fixed
the precise thing pinning exists to prevent.

So the advice is derived from whether the name resolves, instead of assumed.

## The bug this helper had while being written

The first version offered `yazses audio use "pipewire"` when the alias resolved to
`pipewire` — an alias behind an alias. It passed `resolve_input_device`, so a
resolution-only check was not enough; the candidate has to not be a route itself. Caught by
running it, not by reading it, and pinned below.

## Not fixed here

That the hardware names are useless (`sof-hda-dsp: - (hw:0,0)` names no microphone) is what
PortAudio reports for ALSA. Mapping a wpctl node to a PortAudio index needs a PipeWire
client library, which `is_routing_alias`'s own docstring already records as a dependency
this project does not take on for one diagnostic.
"""

from __future__ import annotations

import pytest

from yazses.audio.devices import InputDevice, alias_pin_advice

# The real list from this machine.
ALSA = [
    InputDevice(index=0, name="sof-hda-dsp: - (hw:0,0)", channels=2, is_default=False),
    InputDevice(index=7, name="sysdefault", channels=128, is_default=False),
    InputDevice(index=8, name="pipewire", channels=64, is_default=False),
    InputDevice(index=10, name="default", channels=64, is_default=True),
]
WITH_REAL_MIC = [*ALSA, InputDevice(index=99, name="Blue Yeti", channels=2, is_default=False)]


def test_a_name_the_capture_list_does_not_have_is_not_offered() -> None:
    """The defect: the resolved friendly name printed as the thing to type."""
    advice = alias_pin_advice("Raptor Lake-P/U/H cAVS Digital Microphone", ALSA)
    assert "yazses audio use \"Raptor" not in advice
    assert "cannot select it" in advice
    assert "yazses audio devices" in advice, "a dead end needs somewhere to go next"


def test_a_name_that_does_resolve_is_offered_verbatim() -> None:
    """The opposite failure: advice that never names a command helps nobody."""
    advice = alias_pin_advice("Blue Yeti", WITH_REAL_MIC)
    assert 'yazses audio use "Blue Yeti"' in advice


@pytest.mark.parametrize("alias", ["pipewire", "default", "sysdefault", "pulse"])
def test_an_alias_behind_an_alias_is_never_offered(alias: str) -> None:
    """The bug this helper had while being written.

    `pipewire` resolves against the capture list, so a resolution-only check offered it —
    reproducing the exact failure the advice exists to prevent, one layer down.
    """
    advice = alias_pin_advice(alias, ALSA)
    assert f'audio use "{alias}"' not in advice
    assert "audio devices" in advice


def test_no_resolved_name_still_points_somewhere() -> None:
    """wpctl absent is ordinary, not an error — the line must still be useful."""
    advice = alias_pin_advice(None, ALSA)
    assert "yazses audio devices" in advice


def test_a_machine_with_nothing_but_routes_says_so() -> None:
    """Sending someone to a list with no pinnable entry is another dead end."""
    routes_only = [d for d in ALSA if d.name in {"default", "pipewire", "sysdefault"}]
    advice = alias_pin_advice(None, routes_only)
    assert "nothing to" in advice
    assert "follow whatever the OS points at" in advice


def test_it_is_pure() -> None:
    """No PortAudio, no subprocess, no config — so it is testable without hardware, which
    is how the alias-behind-alias bug was found before it shipped.

    The docstring is deliberately excluded: it *describes* wpctl and the capture list, and
    a naive grep over the whole source failed on its own explanation.
    """
    import ast
    import inspect

    from yazses.audio import devices

    fn = ast.parse(inspect.getsource(devices.alias_pin_advice)).body[0]
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body
    code = "\n".join(ast.unparse(node) for node in body)
    for forbidden in ("sounddevice", "subprocess", "wpctl", "open("):
        assert forbidden not in code, f"{forbidden} in the body of alias_pin_advice"


def test_audio_status_uses_it() -> None:
    """The point of extracting it: the advice and the resolution cannot drift apart."""
    import inspect

    from yazses.cli import audio_status

    assert "alias_pin_advice" in inspect.getsource(audio_status)
