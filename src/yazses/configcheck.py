"""Type-checking and repair for config files, biased toward staying up.

A dictation daemon is only useful if it is running when you reach for the key, so the
rule here is: **a config file must never be able to stop YazSes from starting.** Python
dataclasses enforce nothing at runtime, so before this existed a single mistyped value
sailed through ``load_config`` and detonated later, deep in the pipeline, with a message
that named neither the file nor the key — one quoted number turned every dictation burst
into ``ufunc 'less' did not contain a loop ...`` and the daemon looked perfectly healthy
while transcribing nothing (issue #52). A typo'd *key* was worse still: an unexpected
keyword argument aborted the whole load, so one bad character meant no daemon at all.

Both are now non-fatal. Values that can be repaired are repaired, values that cannot fall
back to their default, unknown keys are dropped, and every one of those decisions is
recorded as a :class:`ConfigProblem` so the daemon can log it, ``doctor`` can show it, and
the user can be told exactly which line to fix. Degrading loudly beats failing silently,
and both beat not starting.

Generic over dataclasses on purpose: it reads the annotations, so new config sections are
covered the day they are added, with nothing to remember.
"""
from __future__ import annotations

import dataclasses
import math
import re
import types
import typing
from dataclasses import dataclass

__all__ = ["ConfigProblem", "build_section", "coerce_value"]

_TRUE = {"true", "yes", "on", "1"}
_FALSE = {"false", "no", "off", "0"}


@dataclass(frozen=True)
class ConfigProblem:
    """One thing wrong in the config file, and what was done about it."""

    section: str
    key: str
    detail: str
    repaired: bool  # True = value salvaged; False = default used, or key dropped

    def __str__(self) -> str:
        where = f"[{self.section}] {self.key}" if self.key else f"[{self.section}]"
        return f"{where}: {self.detail}"


def _unwrap_optional(tp):
    """Return (inner_type, allows_none) for ``X | None``; otherwise (tp, False)."""
    origin = typing.get_origin(tp)
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        allows_none = len(args) != len(typing.get_args(tp))
        if len(args) == 1:
            return args[0], allows_none
        return None, allows_none  # a genuine multi-type union: accept as-is
    return tp, False


def coerce_value(value, tp):
    """Coerce ``value`` to ``tp``. Returns ``(ok, coerced_or_None, note)``.

    ``note`` describes a repair that succeeded, so the caller can report a config that
    works but should still be corrected at the source.
    """
    inner, allows_none = _unwrap_optional(tp)
    if value is None:
        return (True, None, None) if allows_none else (False, None, "is empty")
    if inner is None:  # union we don't reason about — take it as given
        return True, value, None

    origin = typing.get_origin(inner)
    if origin in (list, set, tuple):
        if not isinstance(value, (list, tuple)):
            return False, None, f"should be a list, got {_name(value)}"
        (elem_tp,) = typing.get_args(inner) or (str,)
        out = []
        for item in value:
            ok, coerced, _ = coerce_value(item, elem_tp)
            if not ok:
                return False, None, f"contains a value that is not {_type_name(elem_tp)}"
            out.append(coerced)
        return True, origin(out), None
    if origin is dict:
        if not isinstance(value, dict):
            return False, None, f"should be a table, got {_name(value)}"
        return True, value, None

    # bool BEFORE int: bool is a subclass of int, and `enabled = 1` must not silently
    # become True-by-accident in a way that hides a real mistake in the file.
    if inner is bool:
        if isinstance(value, bool):
            return True, value, None
        if isinstance(value, str):
            low = value.strip().lower()
            if low in _TRUE:
                return True, True, f'should be a bare true, not the string "{value}"'
            if low in _FALSE:
                return True, False, f'should be a bare false, not the string "{value}"'
        return False, None, f"should be true or false, got {_name(value)}"
    if inner is int:
        if isinstance(value, bool):
            return False, None, "should be a number, got true/false"
        if isinstance(value, int):
            return True, value, None
        if isinstance(value, float) and value.is_integer():
            return True, int(value), "should be a whole number"
        if isinstance(value, str):
            try:
                return True, int(value.strip()), f'should be a bare number, not "{value}"'
            except ValueError:
                pass
        return False, None, f"should be a whole number, got {_name(value)}"
    if inner is float:
        if isinstance(value, bool):
            return False, None, "should be a number, got true/false"
        note = None
        if isinstance(value, (int, float)):
            out = float(value)
        elif isinstance(value, str):
            try:
                out = float(value.strip())
                note = f'should be a bare number, not "{value}"'
            except ValueError:
                return False, None, f"should be a number, got {_name(value)}"
        else:
            return False, None, f"should be a number, got {_name(value)}"
        # `nan` and `inf` are floats, so a type check waves them through -- and this
        # module's whole promise is that a bad config yields a working daemon and a
        # ConfigProblem, never a silent oddity. The one that bites is
        # `[accessibility] vad_threshold`: the silence gate is `mean(|audio|) <
        # threshold`, so `inf` discards every burst and dictation types nothing at
        # all, while `nan` makes the comparison false forever and the gate stops
        # gating. Both used to load cleanly with `doctor` reporting no problem.
        if not math.isfinite(out):
            return False, None, f"must be an ordinary number, got {value}"
        return True, out, note
    if inner is str:
        if isinstance(value, str):
            return True, value, None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return True, str(value), f'should be quoted text, e.g. "{value}"'
        return False, None, f"should be text, got {_name(value)}"

    if dataclasses.is_dataclass(inner):
        return True, value, None  # handled by build_section's recursion
    return True, value, None


def _default_of(field):
    """The field's shipped default, or ``None`` if it only has a factory."""
    if field.default is not dataclasses.MISSING:
        return field.default
    return None


def negative_is_impossible(field) -> bool:
    """Does a negative value make this setting meaningless? Derived, not listed.

    Every numeric setting in YazSes is one of two things. Most are magnitudes -- a
    duration, a size, a count, an RMS threshold -- where a negative is not a wrong
    value but an impossible one. A few are genuinely signed: `[hallucination]
    logprob_threshold`, `[reask] threshold` and `[whispermode] tilt_min` are all
    log-probabilities or signed measures and ship negative defaults.

    Rather than hand-maintaining a list of which is which -- a list that would be
    correct on the day it was written and wrong after the next feature -- the shipped
    default decides: a setting whose own default is >= 0 is a magnitude. A new signed
    setting brings its own permission with it.

    This matters because `configcheck` validated *types* only, and `doctor` reports its
    result as **"Config validity: every setting has the expected type"**. A negative
    `vad_threshold` is type-correct and catastrophic: `is_silent` is
    ``mean(abs(audio)) < threshold``, which against a negative threshold is never true,
    so nothing is ever discarded as silence and every burst -- including the ones where
    nobody spoke -- reaches the model to hallucinate on. The user is told their config
    is valid.
    """
    default = _default_of(field)
    if isinstance(default, bool) or not isinstance(default, (int, float)):
        return False
    return default >= 0


#: Settings whose documented values are a closed set, keyed by ``section.key``.
#:
#: Type coercion accepts any string for a `str` field, so a typo was stored verbatim,
#: reported nothing, and `yazses doctor` said "Config validity: every setting is a usable
#: value". What happened next depended on the key and was invisible either way:
#:
#:   [injection] backend = "clipbaord"   -> no branch matches, the auto path runs, and
#:                                          the user believes they forced the clipboard
#:   [injection] target_guard = "of"     -> the daemon tests `!= "off"`, so the guard
#:                                          stays ON for someone switching it off
#:
#: The second is the one that decided this was worth fixing: a misspelled "off" leaves a
#: feature enabled, which is the opposite of what was asked and produces no error.
#:
#: Only closed sets belong here. `[stt] compute_type` is a property of the CPU,
#: `[stt] language` is open, and a model name is whatever is downloadable -- guessing at
#: those would reject valid configs, which is worse than accepting an invalid one.
#:
#: Eight further settings ARE closed sets and are deliberately absent, because each one
#: already fails safe and says so: `[gaze] backend`, `[gaze] zones`, `[stt] engine`,
#: `[emg] mode`, `[cocktail] mode`, `[meeting] vad_backend`, `[voiceprint] backend`,
#: `[polyglot] lid`. An unrecognised value there disables the feature or falls back to the
#: always-available implementation, with a log line naming what happened -- the opposite
#: of `target_guard`, where a misspelling turned a guard ON. Adding them would be eight
#: more chances to reject a value that works, for settings whose failure is already
#: visible. `tests/test_config_enums_are_validated.py` pins that fail-safe behaviour, so
#: if one of them starts falling back to something ENABLED, the exclusion stops being
#: justified and a test says so.
_ENUMS: dict[str, tuple[str, ...]] = {
    "injection.backend": ("auto", "type", "clipboard", "wtype"),
    "injection.target_guard": ("clipboard", "warn", "off"),
}


#: Settings whose entries must be valid regular expressions. Type coercion accepts any
#: string, so `redact_patterns = ["[unclosed"]` was stored, reported nothing, and then
#: raised `re.PatternError` inside `CorpusStore.__init__` -- during daemon startup, which
#: `configcheck` exists to make impossible ("no config file can stop the daemon starting").
#:
#: Reported here, and `learning/capture.py` fails CLOSED on the same input: a redaction
#: pattern the user wrote to scrub secrets must never be silently skipped, so capture is
#: disabled rather than run unredacted.
_REGEX_LISTS: frozenset[str] = frozenset({"learning.redact_patterns"})


def invalid_regexes(section: str, key: str, value) -> list[str]:
    """The entries of ``value`` that are not valid regular expressions. Pure."""
    if f"{section}.{key}" not in _REGEX_LISTS or not isinstance(value, (list, tuple)):
        return []
    bad = []
    for item in value:
        try:
            re.compile(str(item))
        except re.error:
            bad.append(str(item))
    return bad


def enum_values(section: str, key: str) -> tuple[str, ...] | None:
    """The closed set of values for ``section.key``, or None if it is not closed.

    Public so the settings window builds its choices from the same table the loader
    validates against -- two lists would disagree the first time one was extended.
    """
    return _ENUMS.get(f"{section}.{key}")


def build_section(cls, raw, section: str, problems: list[ConfigProblem]):
    """Build dataclass ``cls`` from ``raw``, repairing or dropping anything invalid.

    Never raises for bad input. Anything that cannot be honoured falls back to the field's
    default and is appended to ``problems``.
    """
    if not isinstance(raw, dict):
        problems.append(
            ConfigProblem(section, "", f"should be a table, got {_name(raw)}; ignored", False)
        )
        return cls()

    hints = typing.get_type_hints(cls)
    fields = {f.name: f for f in dataclasses.fields(cls)}
    kwargs = {}

    for key, value in raw.items():
        if key not in fields:
            problems.append(
                ConfigProblem(section, str(key), "is not a known setting; ignored", False)
            )
            continue
        tp = hints.get(key, str)
        inner, _ = _unwrap_optional(tp)
        if dataclasses.is_dataclass(inner) and isinstance(value, dict):
            kwargs[key] = build_section(inner, value, f"{section}.{key}", problems)
            continue
        ok, coerced, note = coerce_value(value, tp)
        if (
            ok
            and not isinstance(coerced, bool)
            and isinstance(coerced, (int, float))
            and coerced < 0
            and negative_is_impossible(fields[key])
        ):
            ok, note = False, f"cannot be negative (got {coerced})"
        if ok and (bad := invalid_regexes(section, key, coerced)):
            problems.append(
                ConfigProblem(
                    section, key,
                    f"is not a valid regular expression: {', '.join(repr(b) for b in bad)}"
                    f"; capture stays off until it is fixed",
                    False,
                )
            )
        allowed = enum_values(section, key)
        if ok and allowed and isinstance(coerced, str):
            if coerced.strip().lower() not in allowed:
                ok = False
                note = (
                    f"is not one of {', '.join(allowed)} (got {coerced!r})"
                )
        if ok:
            if note:
                problems.append(
                    ConfigProblem(section, key, f"{note}; used it anyway", True)
                )
            kwargs[key] = coerced
        else:
            problems.append(
                ConfigProblem(section, key, f"{note}; using the default instead", False)
            )

    try:
        return cls(**kwargs)
    except Exception as exc:  # a default_factory or __post_init__ objected
        problems.append(
            ConfigProblem(section, "", f"could not be applied ({exc}); using defaults", False)
        )
        return cls()


def _name(value) -> str:
    if isinstance(value, bool):
        return "true/false"
    if isinstance(value, str):
        return f'the text "{value}"'
    return f"a {type(value).__name__}"


def _type_name(tp) -> str:
    return getattr(tp, "__name__", str(tp))
