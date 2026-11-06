"""Pure replay oracle for streaming commit safety (spec Phase R0).

Implements ``design/specs/streaming-commit-replay-protocol.md`` sections 2-3: a
deterministic reducer over synthetic event traces that decides what a *safe*
delivery boundary would write to the external target.  It is the **desired
policy oracle**, not a model of the current ``StreamingEngine`` /
``StreamingInjector`` code, so a fixture marked ``known_defect`` is still held
to its ``expect`` block.

Nothing here touches the daemon, config, audio, a clock, the network or any
heavy dependency; it is imported by tests only.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

__all__ = [
    "ReplayFormatError",
    "ReplayResult",
    "Rules",
    "Trace",
    "load_traces",
    "parse_trace",
    "reduce_trace",
]

EVENT_KINDS = frozenset(
    {
        "hold_start",
        "hypothesis",
        "pause",
        "hold_release",
        "handsfree_stop",
        "final_decode",
        "target",
        "stage_commit",
        "stage_discard",
        "late_partial",
        "failure",
    }
)
FAILURE_CATEGORIES = frozenset(
    {"decode", "inject_before_effect", "inject_after_partial_effect", "target_lost"}
)
ACTIVATIONS = frozenset({"hold", "handsfree"})
EXPECT_REQUIRED = (
    "target_writes",
    "staged_chunks",
    "finalizations",
    "no_pre_release_writes",
    "no_forbidden_deletions",
)
EXPECT_OPTIONAL = ("known_defect",)


class ReplayFormatError(ValueError):
    """A trace record does not satisfy the v1 event schema."""


@dataclass(frozen=True)
class Rules:
    """Oracle rules, each switchable so tests can prove a fixture notices a flip."""

    hypothesis_never_writes: bool = True
    finalize_once: bool = True
    gate_on_target: bool = True
    late_partial_dropped: bool = True
    staged_defers_write: bool = True
    empty_final_writes_nothing: bool = True
    failure_revokes_write: bool = True
    never_delete: bool = True


@dataclass(frozen=True)
class Trace:
    id: str
    description: str
    mode: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    expect: dict[str, Any]


@dataclass(frozen=True)
class ReplayResult:
    target_writes: tuple[str, ...]
    staged_chunks: tuple[str, ...]
    finalizations: int
    no_pre_release_writes: bool
    no_forbidden_deletions: bool
    indeterminate: bool = False
    phase: str = "idle"

    def as_expect(self) -> dict[str, Any]:
        return {
            "target_writes": list(self.target_writes),
            "staged_chunks": list(self.staged_chunks),
            "finalizations": self.finalizations,
            "no_pre_release_writes": self.no_pre_release_writes,
            "no_forbidden_deletions": self.no_forbidden_deletions,
        }


# --------------------------------------------------------------------- schema


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _fail(trace_id: object, msg: str) -> ReplayFormatError:
    return ReplayFormatError(f"trace {trace_id!r}: {msg}")


def _check_event(tid: object, i: int, ev: object) -> None:
    if not isinstance(ev, dict):
        raise _fail(tid, f"event {i} is not an object")
    kind = ev.get("kind")
    if kind not in EVENT_KINDS:
        raise _fail(tid, f"event {i} has unknown kind {kind!r}")
    if not _is_int(ev.get("t_ms")) or ev["t_ms"] < 0:
        raise _fail(tid, f"event {i} needs a non-negative integer t_ms")
    if kind in ("hypothesis", "final_decode", "late_partial") and not isinstance(
        ev.get("text"), str
    ):
        raise _fail(tid, f"event {i} ({kind}) needs string text")
    if kind == "pause" and (not _is_int(ev.get("duration_ms")) or ev["duration_ms"] < 0):
        raise _fail(tid, f"event {i} (pause) needs integer duration_ms >= 0")
    if kind == "failure" and ev.get("category") not in FAILURE_CATEGORIES:
        raise _fail(tid, f"event {i} (failure) has unknown category {ev.get('category')!r}")
    if kind == "target":
        if not isinstance(ev.get("focus_id"), str):
            raise _fail(tid, f"event {i} (target) needs string focus_id")
        if not _is_int(ev.get("caret_version")):
            raise _fail(tid, f"event {i} (target) needs integer caret_version")
        if not isinstance(ev.get("editable"), bool):
            raise _fail(tid, f"event {i} (target) needs boolean editable")


def parse_trace(record: object) -> Trace:
    """Schema-validate one decoded JSONL record."""
    if not isinstance(record, dict):
        raise ReplayFormatError("trace record is not an object")
    tid = record.get("id")
    for key in ("id", "description", "mode", "events", "expect"):
        if key not in record:
            raise _fail(tid, f"missing mandatory field {key!r}")
    if not isinstance(tid, str) or not tid:
        raise _fail(tid, "id must be a non-empty string")
    if not isinstance(record["description"], str):
        raise _fail(tid, "description must be a string")
    mode = record["mode"]
    if (
        not isinstance(mode, dict)
        or mode.get("activation") not in ACTIVATIONS
        or not isinstance(mode.get("staged"), bool)
        or not isinstance(mode.get("streaming"), bool)
    ):
        raise _fail(tid, "mode needs activation hold|handsfree and boolean staged/streaming")
    events = record["events"]
    if not isinstance(events, list) or not events:
        raise _fail(tid, "events must be a non-empty list")
    last = -1
    for i, ev in enumerate(events):
        _check_event(tid, i, ev)
        if ev["t_ms"] < last:
            raise _fail(tid, f"event {i} t_ms goes backwards")
        last = ev["t_ms"]
    expect = record["expect"]
    if not isinstance(expect, dict):
        raise _fail(tid, "expect must be an object")
    for key in EXPECT_REQUIRED:
        if key not in expect:
            raise _fail(tid, f"expect missing {key!r}")
    extra = set(expect) - set(EXPECT_REQUIRED) - set(EXPECT_OPTIONAL)
    if extra:
        raise _fail(tid, f"expect has unknown keys {sorted(extra)}")
    for key in ("target_writes", "staged_chunks"):
        v = expect[key]
        if not isinstance(v, list) or not all(isinstance(s, str) for s in v):
            raise _fail(tid, f"expect.{key} must be a list of strings")
    if not _is_int(expect["finalizations"]) or expect["finalizations"] < 0:
        raise _fail(tid, "expect.finalizations must be a non-negative integer")
    for key in ("no_pre_release_writes", "no_forbidden_deletions"):
        if not isinstance(expect[key], bool):
            raise _fail(tid, f"expect.{key} must be boolean")
    if "known_defect" in expect and not (
        isinstance(expect["known_defect"], str) and expect["known_defect"]
    ):
        raise _fail(tid, "expect.known_defect must be a non-empty string")
    return Trace(
        id=tid,
        description=record["description"],
        mode=dict(mode),
        events=tuple(events),
        expect=dict(expect),
    )


def load_traces(lines: Iterable[str]) -> list[Trace]:
    """Parse and validate JSONL text; blank lines are skipped, ids must be unique."""
    traces: list[Trace] = []
    seen: set[str] = set()
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReplayFormatError(f"line {n}: invalid JSON: {exc.msg}") from exc
        trace = parse_trace(record)
        if trace.id in seen:
            raise ReplayFormatError(f"line {n}: duplicate trace id {trace.id!r}")
        seen.add(trace.id)
        traces.append(trace)
    return traces


# -------------------------------------------------------------------- reducer


@dataclass
class _Target:
    focus_id: str = ""
    caret_version: int = 0
    editable: bool = True


@dataclass
class _State:
    phase: str = "idle"
    release_t: int | None = None
    target: _Target = field(default_factory=_Target)
    start_target: _Target = field(default_factory=_Target)
    chunks: list[str] = field(default_factory=list)
    writes: list[tuple[int, str]] = field(default_factory=list)
    deletions: list[int] = field(default_factory=list)
    finalizations: int = 0
    last_hypothesis: str = ""
    last_delivery: tuple[str, str, list[str]] | None = None  # (kind, text, chunks)
    indeterminate: bool = False


def _target_ok(st: _State, rules: Rules) -> bool:
    if not rules.gate_on_target:
        return True
    t, s = st.target, st.start_target
    return t.editable and t.focus_id == s.focus_id and t.caret_version == s.caret_version


def reduce_trace(trace: Trace, rules: Rules | None = None) -> ReplayResult:
    """Reduce ``trace`` to what a safe boundary delivers to the external target."""
    rules = rules or Rules()
    staged = bool(trace.mode["staged"])
    handsfree = trace.mode["activation"] == "handsfree"
    streaming = bool(trace.mode["streaming"])
    st = _State()

    for ev in trace.events:
        kind, t = ev["kind"], ev["t_ms"]
        if kind == "target":
            st.target = _Target(ev["focus_id"], ev["caret_version"], ev["editable"])
        elif kind == "hold_start":
            if st.phase in ("idle", "sealed"):
                st.phase, st.release_t = "recording", None
                st.start_target = replace(st.target)
                st.last_hypothesis = ""
        elif kind == "hypothesis":
            if st.phase != "recording":
                continue
            prev, st.last_hypothesis = st.last_hypothesis, ev["text"]
            if not rules.never_delete and prev and not ev["text"].startswith(prev):
                st.deletions.append(len(prev))
            if (not rules.hypothesis_never_writes) and streaming:
                st.writes.append((t, ev["text"]))
        elif kind == "late_partial":
            if st.phase != "recording" and not rules.late_partial_dropped:
                st.writes.append((t, ev["text"]))
        elif kind == "pause":
            pass  # rule 3: a pause never finalizes a physical hold
        elif kind in ("hold_release", "handsfree_stop"):
            authorised = (kind == "handsfree_stop") == handsfree
            if authorised and st.phase == "recording":
                st.phase, st.release_t = "released", t
        elif kind == "final_decode":
            open_ = st.phase == "released" or (
                not rules.finalize_once and st.phase in ("sealed", "staged_pending")
            )
            if not open_:
                continue
            st.finalizations += 1
            text = ev["text"]
            if rules.empty_final_writes_nothing and not text.strip():
                st.phase = "sealed"
            elif staged and rules.staged_defers_write:
                st.chunks.append(text)
                st.phase = "staged_pending"
            else:
                st.phase = "sealed"
                if _target_ok(st, rules):
                    st.writes.append((t, text))
                    st.last_delivery = ("write", text, [])
        elif kind == "stage_commit":
            if (
                st.phase == "staged_pending"
                and st.chunks
                and not st.indeterminate
                and _target_ok(st, rules)
            ):
                text = " ".join(st.chunks)
                st.last_delivery = ("commit", text, list(st.chunks))
                st.writes.append((t, text))
                st.chunks.clear()
                st.phase = "sealed"
        elif kind == "stage_discard":
            if st.phase == "staged_pending":
                st.chunks.clear()
                st.phase = "sealed"
        elif kind == "failure":
            cat = ev["category"]
            d = st.last_delivery
            if d is None or cat == "decode" or not rules.failure_revokes_write:
                continue
            dkind, text, chunks = d
            for i in range(len(st.writes) - 1, -1, -1):
                if st.writes[i][1] == text:
                    del st.writes[i]
                    break
            if cat == "inject_after_partial_effect":
                st.indeterminate = True  # never restore or retry blindly
            elif dkind == "commit":
                st.chunks = list(chunks)
                st.phase = "staged_pending"
            st.last_delivery = None

    pre_release_ok = all(st.release_t is not None and wt >= st.release_t for wt, _ in st.writes)
    return ReplayResult(
        target_writes=tuple(w for _, w in st.writes),
        staged_chunks=tuple(st.chunks),
        finalizations=st.finalizations,
        no_pre_release_writes=pre_release_ok,
        no_forbidden_deletions=not st.deletions,
        indeterminate=st.indeterminate,
        phase=st.phase,
    )
