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
