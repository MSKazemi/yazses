"""Four more settings in the window, chosen for the way each one can be wrong.

The window had grown from three value settings to six; this adds the next four.
Widgets are the easy half — the reason these four and not four others is that each
has a failure mode a text editor cannot protect you from:

* **compute type** — an unsupported quantisation raises inside the model load, and
  `stt/faster_whisper.py` re-raises it as `ModelUnavailableError`. So the user is
  told the *model* is unavailable and handed three ways to download a model they
  already have. Nothing anywhere mentions quantisation. The supported set is a
  property of the CPU, so the list is asked of ctranslate2 rather than hardcoded.
* **vocabulary** — free text with no wrong answer, except a newline, which would
  produce TOML the loader rejects and cause `configcheck` to repair the whole
  `[stt]` section back to defaults, silently discarding neighbouring settings.
* **no-text-target guard** — the daemon compares this against `"off"` and treats
  everything else as on, so an unrecognised value silently means "clipboard" while
  reading back as whatever was typed.
* **pre-speech padding** — the fix for a symptom nobody connects to a setting: the
  first word of every burst going missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from yazses.settingsui.controller import SettingsController
from yazses.settingsui.controls import (
    PADDING_MAX_MS,
    PADDING_MIN_MS,
    TARGET_GUARDS,
    clamp_padding_ms,
    compute_type_choices,
    target_guard_choices,
)


@dataclass
class _Stt:
    model: str = "base.en"
    language: str = ""
    device: str = "cpu"
    compute_type: str = "int8"
    initial_prompt: str = ""


@dataclass
class _Injection:
    backend: str = "auto"
    target_guard: str = "clipboard"


@dataclass
class _Accessibility:
    pre_speech_padding_ms: int = 300


@dataclass
class _Cfg:
    stt: _Stt = field(default_factory=_Stt)
    injection: _Injection = field(default_factory=_Injection)
    accessibility: _Accessibility = field(default_factory=_Accessibility)


def _controller(cfg: _Cfg | None = None, writes: list | None = None):
    cfg = cfg if cfg is not None else _Cfg()
    writes = writes if writes is not None else []
    ctrl = SettingsController(
        load_config=lambda: cfg,
        writer=lambda section, key, value, quote: writes.append((section, key, value)),
    )
    return ctrl, writes


# ---- compute type ----------------------------------------------------------

def _ctranslate2_or_skip():
    """The real probe, or a skip that says why -- never a failure in this file.

    A compiled extension can fail at *load* rather than at resolution, and on a real
    Windows host importing it raised

        FileNotFoundError: Could not find module '...\\ctranslate2\\ctranslate2.dll'
        (or one of its dependencies)

    because the Microsoft Visual C++ runtime was missing. The three tests below are the
    only ones here that import it, so that machine reported "three failures in the
    settings-controls tests" when what was true was "this install cannot transcribe
    anything". Undoing that misnaming cost a rescued log from a deleted VM.

    `pytest.importorskip` does not cover it -- it catches ImportError, and this is not
    one. The condition itself is asserted by `tests/test_the_decoder_can_load.py`, which
    fails loudly under its own name, and reported to the user by `yazses doctor`. Here it
    is someone else's failure, and `compute_type_choices` has its own tested fallback for
    exactly this case a few tests below.
    """
    try:
        import ctranslate2 as ct2
    except Exception as exc:
        pytest.skip(
            f"ctranslate2 will not load here ({type(exc).__name__}: {exc}) -- see "
            "tests/test_the_decoder_can_load.py, which is the test for that"
        )
    return ct2




def test_the_compute_list_is_what_this_machine_reports():
    """Asked of ctranslate2, not hardcoded — the answer depends on the CPU.

    A fixed list would offer values that load on the developer's box and fail on the
    user's, which is the whole failure this setting is meant to prevent.
    """
    ctranslate2 = _ctranslate2_or_skip()

    expected = sorted(ctranslate2.get_supported_compute_types("cpu"))
    assert compute_type_choices("cpu") == expected


def test_the_list_really_comes_from_the_probe_and_not_a_constant(mocker):
    """Deliberately distinctive, because the honest version of the test below cannot fail.

    This machine's real CPU set is `{int8, int8_float32, int16, float32}` — which is
    exactly the hardcoded fallback. So "the fallback is returned when the probe fails"
    and "the probe's answer is returned" are indistinguishable here: both assertions
    pass whichever branch runs. Feeding the probe an answer no fallback would ever
    contain is the only way to prove the call happens at all.
    """
    ctranslate2 = _ctranslate2_or_skip()

    mocker.patch.object(
        ctranslate2, "get_supported_compute_types", return_value={"int4_imaginary"}
    )
    assert compute_type_choices("cpu") == ["int4_imaginary"]


def test_a_failing_probe_yields_a_usable_list_instead_of_raising(mocker):
    """`get_supported_compute_types` probes the device and raises on a broken CUDA.

    Verified live: `get_supported_compute_types("cuda")` raises RuntimeError on this
    machine. The settings window must still open there — every other setting works,
    and a window that will not open is worse than one whose dropdown is conservative.
    """
    ctranslate2 = _ctranslate2_or_skip()

    from yazses.settingsui.controls import _FALLBACK_COMPUTE_TYPES

    mocker.patch.object(
        ctranslate2, "get_supported_compute_types", side_effect=RuntimeError("no CUDA")
    )
    assert compute_type_choices("cuda") == sorted(_FALLBACK_COMPUTE_TYPES)


def test_the_import_failing_is_also_survivable(mocker):
    """ctranslate2 is a compiled extension; a broken wheel fails at import, not at call."""
    import builtins

    real_import = builtins.__import__

    def _no_ctranslate2(name, *args, **kwargs):
        if name == "ctranslate2":
            raise ImportError("bad wheel")
        return real_import(name, *args, **kwargs)

    mocker.patch.object(builtins, "__import__", _no_ctranslate2)
    assert compute_type_choices("cpu")  # a list, not an exception


def test_a_configured_compute_type_is_kept_even_when_unsupported_here():
    """Same rule as the model list: never silently replace a hand-edited value.

    The config may have been written on another machine, or for a CUDA build.
    """
    choices = compute_type_choices("cpu", current="float16")
    assert choices[0] == "float16"


def test_setting_a_supported_compute_type_writes_it():
    ctrl, writes = _controller()
    supported = compute_type_choices("cpu")
    assert ctrl.set_compute_type(supported[0]).ok
    assert writes == [("stt", "compute_type", supported[0])]


def test_an_unsupported_compute_type_is_refused_and_names_the_alternatives():
    """The refusal replaces a misdiagnosis at next start with an accurate message now."""
    ctrl, writes = _controller()
    result = ctrl.set_compute_type("float64")
    assert not result.ok
    assert "float64" in result.error
    assert "int8" in result.error, f"must list what is available: {result.error}"
    assert writes == [], "nothing may be written when the value is refused"


def test_an_unsupported_value_already_in_the_config_is_still_refused():
    """The subtle one: showing a value must not make it settable.

    `compute_type_choices` deliberately keeps a configured-but-unsupported value so
    the box can display it. If the refusal used that same list, then a config already
    holding `float16` would let the user re-select and save it — the check would pass
    precisely because the bad value was already there.
    """
    cfg = _Cfg(stt=_Stt(compute_type="float16"))
    ctrl, writes = _controller(cfg)
    assert "float16" in compute_type_choices("cpu", current="float16")
    assert not ctrl.set_compute_type("float16").ok
    assert writes == []


def test_an_empty_compute_type_is_refused_rather_than_defaulted():
    ctrl, _ = _controller()
    assert not ctrl.set_compute_type("").ok


def test_the_device_is_read_from_the_config_when_not_given():
    """cpu and cuda report different sets, so the check must know which one."""
    ctrl, _ = _controller(_Cfg(stt=_Stt(device="cpu")))
    supported = compute_type_choices("cpu")
    assert ctrl.set_compute_type(supported[0]).ok


# ---- vocabulary (initial_prompt) -------------------------------------------


def test_setting_the_vocabulary_writes_it():
    ctrl, writes = _controller()
    assert ctrl.set_initial_prompt("YazSes, Kubernetes, Seyedkazemi").ok
    assert writes == [("stt", "initial_prompt", "YazSes, Kubernetes, Seyedkazemi")]


def test_an_empty_vocabulary_is_a_real_choice_and_is_written():
    """Clearing the box means "no priming" — it is not an unset field."""
    ctrl, writes = _controller(_Cfg(stt=_Stt(initial_prompt="old terms")))
    assert ctrl.set_initial_prompt("").ok
    assert writes == [("stt", "initial_prompt", "")]


def test_newlines_are_collapsed_rather_than_written_into_toml():
    """A literal newline makes the file unparseable, and the repair is destructive.

    `configcheck` would fall back to defaults for the whole `[stt]` section — so a
    pasted two-line vocabulary would silently reset the model and the language too.
    """
    ctrl, writes = _controller()
    assert ctrl.set_initial_prompt("first line\nsecond\tline  ").ok
    assert writes == [("stt", "initial_prompt", "first line second line")]


def test_a_failed_vocabulary_write_is_reported_not_raised():
    def _boom(*_args):
        raise OSError("read-only config")

    ctrl = SettingsController(load_config=_Cfg, writer=_boom)
    result = ctrl.set_initial_prompt("anything")
    assert not result.ok
    assert "read-only config" in result.error


# ---- no-text-target guard --------------------------------------------------


def test_every_guard_choice_is_accepted():
    for _label, value in TARGET_GUARDS:
        ctrl, writes = _controller()
        assert ctrl.set_target_guard(value).ok, value
        assert writes == [("injection", "target_guard", value)]


def test_the_guard_labels_say_what_happens_rather_than_naming_the_value():
    """"clipboard" does not tell anyone what clipboard means here."""
    labels = [label for label, _value in TARGET_GUARDS]
    assert all(len(label.split()) > 2 for label in labels), labels


def test_an_unknown_guard_is_refused_because_it_would_silently_mean_clipboard():
    ctrl, writes = _controller()
    result = ctrl.set_target_guard("maybe")
    assert not result.ok
    assert "clipboard" in result.error
    assert writes == []


def test_a_configured_guard_outside_the_list_is_still_shown():
    rows = target_guard_choices(current="something-custom")
    assert rows[0][1] == "something-custom"


# ---- pre-speech padding ----------------------------------------------------


def test_setting_the_padding_writes_an_int():
    ctrl, writes = _controller()
    assert ctrl.set_pre_speech_padding(450).ok
    assert writes == [("accessibility", "pre_speech_padding_ms", 450)]


@pytest.mark.parametrize(
    "given,expected",
    [(-100, PADDING_MIN_MS), (99999, PADDING_MAX_MS), (300.6, 301), ("250", 250)],
)
def test_the_padding_is_clamped_not_refused(given, expected):
    """A spin box cannot produce an out-of-range value, so refusing would be API misuse.

    Dropping the edit silently would be worse than pinning it to the edge.
    """
    assert clamp_padding_ms(given) == expected


def test_a_non_numeric_padding_is_refused_because_it_would_break_the_config():
    """Writing a string into an int key makes the loader repair the section.

    That repair discards neighbouring settings the user never touched, so this is
    refused rather than coerced.
    """
    ctrl, writes = _controller()
    result = ctrl.set_pre_speech_padding("loud")
    assert not result.ok
    assert "milliseconds" in result.error
    assert writes == []


def test_the_padding_is_written_unquoted():
    """Quoting it would store "300" and the loader would then repair it away."""
    seen = []
    ctrl = SettingsController(
        load_config=_Cfg,
        writer=lambda section, key, value, quote: seen.append(quote),
    )
    assert ctrl.set_pre_speech_padding(300).ok
    assert seen == [False]


# ---- the model carries them, or the widgets open on the wrong values -------


def test_the_settings_model_reads_all_four_from_the_config():
    """A widget built from a default rather than the file writes it on the next Apply.

    That is how a settings window quietly resets a value the user never touched.
    """
    from yazses.config import Config
    from yazses.settingsui.model import build_settings_model

    cfg = Config()
    cfg.stt.compute_type = "float32"
    cfg.stt.initial_prompt = "Kubernetes"
    cfg.stt.device = "cpu"
    cfg.injection.target_guard = "warn"
    cfg.accessibility.pre_speech_padding_ms = 500

    model = build_settings_model(cfg)

    assert model.compute_type == "float32"
    assert model.initial_prompt == "Kubernetes"
    assert model.stt_device == "cpu"
    assert model.target_guard == "warn"
    assert model.pre_speech_padding_ms == 500
