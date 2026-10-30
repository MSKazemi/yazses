"""Guards for the synthetic multimodal HCI lab under ``examples/hci-hf-lab/``.

The lab is a static research prototype, not a product feature. What must stay true:

* it is self-contained: no network, no device or microphone API, no external asset;
* its fixtures are synthetic and match schema ``1.0`` (issue #699), which is maintained
  next to them in ``fixtures.schema.json``;
* the resolver, run under Node when available, agrees with every fixture;
* the page keeps the accessibility basics it was built with.

``jsonschema`` is not guaranteed to be installed, so the schema check is a small
hand-rolled validator, and the tests below prove it rejects bad input.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "examples" / "hci-hf-lab"

APP_FILES = ("index.html", "style.css", "app.js", "resolver.js", "fixtures.js")
MODALITIES = {"voice_intent", "gaze", "face", "emg", "eeg_eog_experimental"}
DECISIONS = {"accept", "ask_confirmation", "abstain", "stop"}
QUALITIES = {"good", "degraded", "unknown"}
OUTCOMES = {"previewed", "awaiting_confirmation", "nothing_proposed", "stopped"}
OUTCOME_OF = {"accept": "previewed", "ask_confirmation": "awaiting_confirmation",
              "abstain": "nothing_proposed", "stop": "stopped"}
REQUIRED_IDS = {
    "correct_target",
    "low_confidence",
    "stale_sensor",
    "conflicting_modalities",
    "muscle_hold_release",
    "accidental_blink",
    "confirmation_required",
    "emergency_stop",
    "out_of_order_sample",
    "emg_hold_chatter",
    "ambiguous_gaze_edge",
    "untrusted_target",
    "sensor_recovery",
}


def _read(name: str) -> str:
    return (LAB / name).read_text(encoding="utf-8")


def _load_fixtures() -> dict[str, Any]:
    text = _read("fixtures.js").strip()
    prefix = "window.HCI_FIXTURES ="
    assert text.startswith(prefix), "fixtures.js must be exactly `window.HCI_FIXTURES = <JSON>;`"
    assert text.endswith(";")
    return json.loads(text[len(prefix) : -1])


# --------------------------------------------------------------------------------------
# A small validator for schema 1.0. It mirrors fixtures.schema.json for the
# properties the tests care about; the schema file stays the documentation.
# --------------------------------------------------------------------------------------


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _confidences(node: Any, path: str = "") -> list[tuple[str, Any]]:
    """Every value stored under a key ending in ``confidence`` (recursing into dicts)."""
    found: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            where = f"{path}.{key}" if path else key
            if key.endswith("confidence"):
                if isinstance(value, dict):
                    found.extend((f"{where}.{k}", v) for k, v in value.items())
                else:
                    found.append((where, value))
            else:
                found.extend(_confidences(value, where))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found.extend(_confidences(value, f"{path}[{i}]"))
    return found


def _quality(stream: dict[str, Any], minimum: float | None, max_age: int) -> str:
    """What `quality` must say for a stream, given the thresholds."""
    conf = stream.get("confidence")
    if conf is None or minimum is None:
        return "unknown"
    return "degraded" if conf < minimum or stream.get("age_ms", 0) > max_age else "good"


def _validate_timeline(sid: str, sc: dict[str, Any], errors: list[str]) -> None:
    events = sc.get("timeline", [])
    if not events:
        errors.append(f"{sid}: empty timeline")
        return
    for i, event in enumerate(events):
        t = event.get("t_ms")
        if not _is_int(t) or t < 0:
            errors.append(f"{sid}: malformed timestamp {t!r}")
        if event.get("seq") != i + 1:
            errors.append(f"{sid}: seq must be {i + 1} (arrival order, from 1), not {event.get('seq')!r}")
    stamps = [e.get("t_ms") for e in events if _is_int(e.get("t_ms"))]
    highest = -1
    for event in events:
        t = event.get("t_ms")
        if not _is_int(t):
            continue
        late = event.get("out_of_order") is True
        if late and t >= highest:
            errors.append(f"{sid}: seq {event.get('seq')} is flagged out_of_order but is not earlier than a prior event")
        if not late and t < highest:
            errors.append(f"{sid}: timeline is not monotonic at seq {event.get('seq')}")
        highest = max(highest, t)
    at = sc.get("decision_at_ms")
    if not _is_int(at) or at < 0 or (stamps and at < max(stamps)):
        errors.append(f"{sid}: decision_at_ms {at!r} must be an int >= the last event")


EVENT_SOURCES = {"system", "gaze", "voice", "activation"}
ID_PATTERN = re.compile(r"^[a-z0-9_]+$")


def _in_range(value: Any, low: float, high: float) -> bool:
    return _is_num(value) and low <= value <= high


def _validate_structure(doc: dict[str, Any], errors: list[str]) -> None:
    """Ranges, enums, id pattern and references: what the JSON Schema says, since it is never executed."""
    kinds = {k.get("id") for k in doc.get("activation_kinds", [])}
    extra = set((doc.get("thresholds", {}).get("activation_min_confidence") or {})) - (kinds - {"none"})
    if extra:
        errors.append(f"thresholds.activation_min_confidence names unknown kinds {sorted(extra)}")
    seen_windows: set[Any] = set()
    for w in doc.get("desktop", {}).get("windows", []):
        if w.get("id") in seen_windows:
            errors.append(f"window {w.get('id')!r}: duplicate id")
        seen_windows.add(w.get("id"))
        rect = w.get("rect", {})
        for key in ("x", "y", "w", "h"):
            if not _in_range(rect.get(key), 0, 100):
                errors.append(f"window {w.get('id')!r}: rect.{key} {rect.get(key)!r} must be a number in [0, 100]")


def _validate_scenario_structure(sid: str, sc: dict[str, Any], doc: dict[str, Any], errors: list[str]) -> None:
    window_ids = {w.get("id") for w in doc.get("desktop", {}).get("windows", [])}
    intent_ids = {i.get("id") for i in doc.get("intents", [])}
    kinds = {k.get("id") for k in doc.get("activation_kinds", [])}
    if not isinstance(sc.get("id"), str) or not ID_PATTERN.match(sc["id"]):
        errors.append(f"{sid}: id must match ^[a-z0-9_]+$")
    if not isinstance(sc.get("negative_example"), bool):
        errors.append(f"{sid}: negative_example must be a boolean")
    mods = sc.get("modality")
    if isinstance(mods, list) and len(mods) != len(set(mods)):
        errors.append(f"{sid}: modality has duplicates")
    intended = sc.get("intended_target")
    if intended is not None and intended not in window_ids:
        errors.append(f"{sid}: intended_target {intended!r} is not a window id")
    for event in sc.get("timeline", []):
        if event.get("source") not in EVENT_SOURCES:
            errors.append(f"{sid}: timeline source {event.get('source')!r} not one of {sorted(EVENT_SOURCES)}")
        if not isinstance(event.get("event"), str) or not event["event"]:
            errors.append(f"{sid}: timeline event needs a name")

    inputs = sc.get("inputs", {})
    gaze, voice, act = inputs.get("gaze", {}), inputs.get("voice", {}), inputs.get("activation", {})
    if not isinstance(inputs.get("emergency_stop"), bool):
        errors.append(f"{sid}: inputs.emergency_stop must be a boolean")
    for stream, keys in (
        ("gaze", ("connected", "x", "y", "confidence", "age_ms", "quality")),
        ("voice", ("intent", "confidence", "target_ref")),
        ("activation", ("kind", "confidence", "age_ms", "hold_ms", "bounce_count", "bounce_gap_ms", "quality")),
    ):
        for key in keys:
            if key not in inputs.get(stream, {}):
                errors.append(f"{sid}: inputs.{stream}.{key} is missing")
    if not isinstance(gaze.get("connected"), bool):
        errors.append(f"{sid}: inputs.gaze.connected must be a boolean")
    for axis in ("x", "y"):
        if not _in_range(gaze.get(axis), 0, 100):
            errors.append(f"{sid}: inputs.gaze.{axis} {gaze.get(axis)!r} must be a number in [0, 100]")
    if voice.get("intent") is not None and voice.get("intent") not in intent_ids:
        errors.append(f"{sid}: inputs.voice.intent {voice.get('intent')!r} is not a known intent")
    if voice.get("target_ref") is not None and voice.get("target_ref") not in window_ids:
        errors.append(f"{sid}: inputs.voice.target_ref {voice.get('target_ref')!r} is not a window id")
    if act.get("kind") not in kinds:
        errors.append(f"{sid}: inputs.activation.kind {act.get('kind')!r} is not a known activation kind")
    count, gap = act.get("bounce_count"), act.get("bounce_gap_ms")
    if not _is_int(count) or count < 0:
        errors.append(f"{sid}: inputs.activation.bounce_count {count!r} must be a non-negative int")
    elif count == 0 and gap is not None:
        errors.append(f"{sid}: bounce_gap_ms must be null when bounce_count is 0")
    elif count > 0 and (not _is_int(gap) or gap < 0):
        errors.append(f"{sid}: bounce_gap_ms {gap!r} must be a non-negative int when bounce_count > 0")


def validate_fixtures(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if doc.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    if doc.get("synthetic") is not True:
        errors.append("top-level synthetic must be true")
    if doc.get("license") != "Apache-2.0":
        errors.append("license must be the SPDX id Apache-2.0")
    for key in ("provenance", "generator", "thresholds", "desktop", "intents", "activation_kinds"):
        if key not in doc:
            errors.append(f"missing top-level key {key}")
    consent = doc.get("consent")
    if not isinstance(consent, dict) or consent.get("required") is not False or not consent.get("reason"):
        errors.append("consent must state required: false and a reason (synthetic data records no person)")

    th = doc.get("thresholds", {})
    margin = th.get("ambiguity_margin_pct")
    if not _is_num(margin) or not 0 <= margin <= 100:
        errors.append(f"thresholds.ambiguity_margin_pct {margin!r} must be a number in [0, 100]")
    max_age = th.get("max_age_ms", 0)

    unknown_ok = ("inputs.gaze.confidence", "inputs.activation.confidence")
    for where, value in _confidences(doc):
        if value is None and where.endswith(unknown_ok):
            continue  # null means unknown, which is not the same as zero
        if not _is_num(value) or not 0 <= value <= 1:
            errors.append(f"{where}: confidence {value!r} not in [0, 1]")

    _validate_structure(doc, errors)
    windows = doc.get("desktop", {}).get("windows", [])
    window_ids = {w.get("id") for w in windows}
    for w in windows:
        if not isinstance(w.get("trusted"), bool):
            errors.append(f"window {w.get('id')!r}: trusted must be a boolean")
    scenarios = doc.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) < 14:
        errors.append("need at least 14 scenarios")
        return errors
    seen: set[str] = set()
    for sc in scenarios:
        sid = sc.get("id", "<no id>")
        if sid in seen:
            errors.append(f"{sid}: duplicate id")
        seen.add(sid)
        if sc.get("synthetic") is not True:
            errors.append(f"{sid}: synthetic must be true")
        mods = sc.get("modality")
        if not isinstance(mods, list) or not mods:
            errors.append(f"{sid}: modality must be a non-empty list")
        else:
            for m in mods:
                if m not in MODALITIES:
                    errors.append(f"{sid}: unknown modality {m!r}")
        expected = sc.get("expected", {})
        decision = expected.get("decision")
        if decision not in DECISIONS:
            errors.append(f"{sid}: expected.decision {decision!r} not one of {sorted(DECISIONS)}")
        for key in ("intent", "target", "outcome"):
            if key not in expected:
                errors.append(f"{sid}: expected.{key} is missing (use null for none)")
        target = expected.get("target")
        if target is not None and target not in window_ids:
            errors.append(f"{sid}: expected.target {target!r} is not a window id")
        outcome = expected.get("outcome")
        if outcome not in OUTCOMES:
            errors.append(f"{sid}: expected.outcome {outcome!r} not one of {sorted(OUTCOMES)}")
        elif decision in DECISIONS and outcome != OUTCOME_OF[decision]:
            errors.append(f"{sid}: expected.outcome {outcome!r} does not follow decision {decision!r}")
        if "intended_target" not in sc:
            errors.append(f"{sid}: missing intended_target (use null if none)")
        if "inputs" not in sc:
            errors.append(f"{sid}: missing inputs")

        _validate_timeline(sid, sc, errors)
        _validate_scenario_structure(sid, sc, doc, errors)

        inputs = sc.get("inputs", {})
        for stream, keys in (("gaze", ("age_ms",)), ("activation", ("age_ms", "hold_ms"))):
            for k in keys:
                v = inputs.get(stream, {}).get(k)
                if not _is_int(v) or v < 0:
                    errors.append(f"{sid}: inputs.{stream}.{k} {v!r} must be a non-negative int")
        gaze = inputs.get("gaze", {})
        act = inputs.get("activation", {})
        for name, stream, minimum in (
            ("gaze", gaze, th.get("gaze_min_confidence") if gaze.get("connected") else None),
            ("activation", act, (th.get("activation_min_confidence") or {}).get(act.get("kind"))),
        ):
            quality = stream.get("quality")
            if quality not in QUALITIES:
                errors.append(f"{sid}: inputs.{name}.quality {quality!r} not one of {sorted(QUALITIES)}")
            elif quality != _quality(stream, minimum, max_age):
                errors.append(
                    f"{sid}: inputs.{name}.quality {quality!r} disagrees with its confidence and age "
                    f"(expected {_quality(stream, minimum, max_age)!r})"
                )
    return errors


# --------------------------------------------------------------------------------------
# Fixtures and schema
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fixtures() -> dict[str, Any]:
    return _load_fixtures()


def test_fixtures_parse_and_validate(fixtures: dict[str, Any]) -> None:
    assert validate_fixtures(fixtures) == []


def test_required_scenarios_are_present(fixtures: dict[str, Any]) -> None:
    ids = {s["id"] for s in fixtures["scenarios"]}
    assert REQUIRED_IDS <= ids
    assert len(ids) >= 21
    negatives = [s["id"] for s in fixtures["scenarios"] if s["negative_example"]]
    assert len(negatives) >= 2, "issue #699 asks for negative examples, not only successes"


# The ten scenarios issue #699 lists, mapped to the fixtures that cover them.
ISSUE_699_SCENARIOS = {
    "correct coarse gaze + spoken reference": ("gaze_plus_voice", "correct_target"),
    "contradictory voice and gaze targets": ("conflicting_modalities",),
    "missing or low-confidence camera signal": ("low_confidence", "sensor_disconnection"),
    "stale observation and out-of-order timestamps": ("stale_sensor", "out_of_order_sample"),
    "muscle hold/release with bounce": ("muscle_hold_release", "emg_hold_chatter"),
    "accidental blink double-event": ("accidental_blink",),
    "ambiguous or untrusted target requiring abstention": ("ambiguous_gaze_edge", "untrusted_target"),
    "destructive command requiring confirmation": ("confirmation_required",),
    "stop, fallback and recovery on a missing sensor": ("emergency_stop", "sensor_disconnection", "sensor_recovery"),
    "false activations and negative examples": ("false_activation", "muscle_hold_release", "accidental_blink"),
}


def test_every_scenario_issue_699_lists_is_covered(fixtures: dict[str, Any]) -> None:
    by_id = {s["id"]: s for s in fixtures["scenarios"]}
    for need, ids in ISSUE_699_SCENARIOS.items():
        missing = [i for i in ids if i not in by_id]
        assert not missing, f"{need}: no fixture {missing}"
    # The two scenarios that were gaps are covered by what they actually exercise.
    chatter = by_id["emg_hold_chatter"]["inputs"]["activation"]
    assert chatter["kind"] == "emg_hold" and chatter["bounce_count"] >= 1
    late = [e for e in by_id["out_of_order_sample"]["timeline"] if e.get("out_of_order")]
    assert late, "out_of_order_sample must contain an event flagged out_of_order"
    assert by_id["untrusted_target"]["expected"]["decision"] == "abstain"
    assert any(e["event"] == "reconnect" for e in by_id["sensor_recovery"]["timeline"])
    assert by_id["sensor_recovery"]["expected"]["decision"] == "accept"


def test_an_unknown_confidence_is_null_not_zero(fixtures: dict[str, Any]) -> None:
    disconnected = next(s for s in fixtures["scenarios"] if s["id"] == "sensor_disconnection")
    gaze = disconnected["inputs"]["gaze"]
    assert gaze["connected"] is False and gaze["confidence"] is None and gaze["quality"] == "unknown"


def test_fixture_ages_agree_with_the_timeline(fixtures: dict[str, Any]) -> None:
    """A stream's age_ms must equal decision_at_ms minus its last sample/activation event."""
    for sc in fixtures["scenarios"]:
        inputs = sc["inputs"]
        want = {
            ("gaze", "sample"): inputs["gaze"]["age_ms"] if inputs["gaze"]["connected"] else None,
            ("activation", "activation"): (
                inputs["activation"]["age_ms"] if inputs["activation"]["kind"] != "none" else None
            ),
        }
        for (source, event), age in want.items():
            times = [e["t_ms"] for e in sc["timeline"] if e["source"] == source and e["event"] == event]
            if age is None:
                continue
            assert times, f"{sc['id']}: no {source}/{event} event for a present stream"
            assert sc["decision_at_ms"] - times[-1] == age, f"{sc['id']}: {source} age disagrees"


def test_schema_file_agrees_with_the_validator(fixtures: dict[str, Any]) -> None:
    schema = json.loads(_read("fixtures.schema.json"))
    assert schema["properties"]["schema_version"]["const"] == fixtures["schema_version"]
    defs = schema["$defs"]
    assert set(defs["modality"]["enum"]) == MODALITIES
    assert set(defs["decision"]["enum"]) == DECISIONS
    assert set(defs["quality"]["enum"]) == QUALITIES
    assert set(defs["outcome"]["enum"]) == OUTCOMES
    assert "#699" in schema["description"], "the schema must name the issue that owns it"
    assert "provisional" not in schema["description"].lower()


def _mutated(fixtures: dict[str, Any], fn: Any) -> list[str]:
    doc = copy.deepcopy(fixtures)
    fn(doc)
    return validate_fixtures(doc)


@pytest.mark.parametrize(
    ("label", "mutate", "needle"),
    [
        ("malformed timestamp", lambda d: d["scenarios"][0]["timeline"][1].update(t_ms="12:00"), "malformed timestamp"),
        ("negative timestamp", lambda d: d["scenarios"][0]["timeline"][1].update(t_ms=-5), "malformed timestamp"),
        ("fractional timestamp", lambda d: d["scenarios"][0]["timeline"][1].update(t_ms=1.5), "malformed timestamp"),
        ("non-monotonic", lambda d: d["scenarios"][0]["timeline"].reverse(), "not monotonic"),
        ("unknown modality", lambda d: d["scenarios"][0]["modality"].append("telepathy"), "unknown modality"),
        ("confidence 1.7", lambda d: d["scenarios"][0]["inputs"]["gaze"].update(confidence=1.7), "not in [0, 1]"),
        ("missing synthetic", lambda d: d["scenarios"][0].pop("synthetic"), "synthetic must be true"),
        ("synthetic false", lambda d: d.update(synthetic=False), "synthetic must be true"),
        ("missing expected decision", lambda d: d["scenarios"][0]["expected"].pop("decision"), "expected.decision"),
        ("bad decision value", lambda d: d["scenarios"][0]["expected"].update(decision="yes"), "expected.decision"),
        ("too few scenarios", lambda d: d["scenarios"].__delitem__(slice(3, None)), "at least 14"),
        ("wrong schema version", lambda d: d.update(schema_version="0.1-prototype"), "schema_version must be"),
        ("missing consent", lambda d: d.pop("consent"), "consent must state"),
        ("consent required", lambda d: d["consent"].update(required=True), "consent must state"),
        ("missing seq", lambda d: d["scenarios"][0]["timeline"][1].pop("seq"), "seq must be"),
        ("seq out of arrival order", lambda d: d["scenarios"][0]["timeline"][1].update(seq=9), "seq must be"),
        (
            "out_of_order flag on an in-order event",
            lambda d: d["scenarios"][0]["timeline"][2].update(out_of_order=True),
            "not earlier than a prior event",
        ),
        ("unknown quality", lambda d: d["scenarios"][0]["inputs"]["gaze"].update(quality="great"), "quality"),
        (
            "quality disagrees with confidence",
            lambda d: d["scenarios"][0]["inputs"]["gaze"].update(quality="degraded"),
            "disagrees",
        ),
        (
            "unknown confidence with quality good",
            lambda d: d["scenarios"][0]["inputs"]["gaze"].update(confidence=None),
            "disagrees",
        ),
        ("missing outcome", lambda d: d["scenarios"][0]["expected"].pop("outcome"), "expected.outcome"),
        (
            "outcome that does not follow the decision",
            lambda d: d["scenarios"][0]["expected"].update(outcome="stopped"),
            "does not follow decision",
        ),
        ("missing intent candidate", lambda d: d["scenarios"][0]["expected"].pop("intent"), "expected.intent"),
        ("window without trusted flag", lambda d: d["desktop"]["windows"][0].pop("trusted"), "trusted must be"),
        ("gaze x out of range", lambda d: d["scenarios"][0]["inputs"]["gaze"].update(x=150), "inputs.gaze.x"),
        ("rect wider than the desktop", lambda d: d["desktop"]["windows"][0]["rect"].update(w=200), "rect.w"),
        ("duplicate window id", lambda d: d["desktop"]["windows"][1].update(id="notes"), "duplicate id"),
        ("unknown timeline source", lambda d: d["scenarios"][0]["timeline"][1].update(source="bogus"), "timeline source"),
        ("negative bounce count", lambda d: d["scenarios"][0]["inputs"]["activation"].update(bounce_count=-1), "bounce_count"),
        (
            "negative bounce gap",
            lambda d: d["scenarios"][0]["inputs"]["activation"].update(bounce_count=1, bounce_gap_ms=-5),
            "bounce_gap_ms",
        ),
        (
            "bounce gap with no bounce",
            lambda d: d["scenarios"][0]["inputs"]["activation"].update(bounce_gap_ms=40),
            "must be null when bounce_count is 0",
        ),
        (
            "bounce without a gap",
            lambda d: d["scenarios"][0]["inputs"]["activation"].update(bounce_count=2),
            "bounce_gap_ms",
        ),
        ("bad scenario id", lambda d: d["scenarios"][0].update(id="Bad Id"), "id must match"),
        ("negative_example not a bool", lambda d: d["scenarios"][0].update(negative_example="no"), "negative_example"),
        ("duplicate modality", lambda d: d["scenarios"][0]["modality"].append(d["scenarios"][0]["modality"][0]), "duplicates"),
        (
            "threshold for an unknown kind",
            lambda d: d["thresholds"]["activation_min_confidence"].update(telepathy=0.5),
            "unknown kinds",
        ),
        ("missing emergency_stop", lambda d: d["scenarios"][0]["inputs"].pop("emergency_stop"), "emergency_stop"),
        ("missing bounce_count", lambda d: d["scenarios"][0]["inputs"]["activation"].pop("bounce_count"), "bounce_count"),
        (
            "voice names a window that does not exist",
            lambda d: d["scenarios"][0]["inputs"]["voice"].update(target_ref="nonexistent"),
            "target_ref",
        ),
        ("intended target that does not exist", lambda d: d["scenarios"][0].update(intended_target="nowhere"), "intended_target"),
        ("unknown spoken intent", lambda d: d["scenarios"][0]["inputs"]["voice"].update(intent="telepathy"), "known intent"),
        (
            "unknown activation kind",
            lambda d: d["scenarios"][0]["inputs"]["activation"].update(kind="telepathy"),
            "known activation kind",
        ),
        (
            "ambiguity margin out of range",
            lambda d: d["thresholds"].update(ambiguity_margin_pct=250),
            "ambiguity_margin_pct",
        ),
    ],
)
def test_validator_rejects_bad_fixtures(fixtures: dict[str, Any], label: str, mutate: Any, needle: str) -> None:
    errors = _mutated(fixtures, mutate)
    assert any(needle in e for e in errors), f"{label}: validator said {errors}"


# --------------------------------------------------------------------------------------
# Self-containment: no network, no device APIs
# --------------------------------------------------------------------------------------

FORBIDDEN_IDENTIFIERS = (
    "getUserMedia",
    "mediaDevices",
    "MediaRecorder",
    "SpeechRecognition",
    "webkitSpeechRecognition",
    "fetch(",
    "XMLHttpRequest",
    "WebSocket",
    "sendBeacon",
    "EventSource",
    "importScripts",
    "eval(",
    "new Function",
    "localStorage",
    "sessionStorage",
    "indexedDB",
    "navigator.bluetooth",
    "navigator.hid",
    "navigator.serial",
    "navigator.usb",
)


@pytest.mark.parametrize("name", APP_FILES)
def test_app_files_have_no_external_urls(name: str) -> None:
    urls = re.findall(r"https?://\S+", _read(name))
    assert not urls, f"{name} references external URLs: {urls}"


@pytest.mark.parametrize("name", APP_FILES)
def test_app_files_use_no_device_or_network_api(name: str) -> None:
    text = _read(name)
    hits = [token for token in FORBIDDEN_IDENTIFIERS if token in text]
    assert not hits, f"{name} uses forbidden identifiers: {hits}"


EVAL_FILES = ("eval/replay.js", "eval/replay.test.js", "eval/make_manifest.js")
NONDETERMINISTIC = ("Date.now", "new Date", "Math.random", "performance.now", "process.hrtime")
NODE_NETWORK_OR_SHELL = ('require("node:http', 'require("http', 'require("node:https', 'require("https',
                         'require("node:net', 'require("net', "child_process", "node:dgram", "node:dns")


@pytest.mark.parametrize("name", EVAL_FILES)
def test_eval_files_are_offline_and_deterministic(name: str) -> None:
    text = _read(name)
    assert not re.findall(r"https?://\S+", text), f"{name} references an external URL"
    hits = [t for t in FORBIDDEN_IDENTIFIERS + NONDETERMINISTIC + NODE_NETWORK_OR_SHELL if t in text]
    assert not hits, f"{name} uses forbidden identifiers: {hits}"


def test_index_loads_only_local_assets() -> None:
    html = _read("index.html")
    refs = re.findall(r"""<(?:script|link|img)\b[^>]*?\b(?:src|href)=["']([^"']+)["']""", html)
    assert refs, "the page should load its own script/style/logo"
    for ref in refs:
        assert not re.match(r"^(?:[a-z][a-z0-9+.-]*:)?//", ref, re.I), f"external reference: {ref}"
        assert (LAB / ref).is_file(), f"index.html references a missing file: {ref}"
    assert "type=\"module\"" not in html, "ES modules are blocked on file://"
    assert "@import" not in _read("style.css")
    assert "font-face" not in _read("style.css"), "no web fonts"


def test_logo_is_the_canonical_icon() -> None:
    assert (LAB / "assets" / "logo.svg").read_bytes() == (ROOT / "contrib" / "icons" / "yazses.svg").read_bytes()


# --------------------------------------------------------------------------------------
# README / dataset card
# --------------------------------------------------------------------------------------


def test_readme_front_matter_is_a_static_space() -> None:
    readme = _read("README.md")
    assert readme.startswith("---\n")
    front = readme.split("---\n", 2)[1]
    meta = dict(re.findall(r"^(\w+):\s*(.*?)\s*$", front, re.M))
    assert meta["sdk"] == "static"
    assert meta["license"] == "apache-2.0"
    assert 0 < len(meta["short_description"]) <= 60
    assert meta["title"] == "YazSes Multimodal HCI Lab (synthetic)"
    for issue in ("#692", "#693", "#699"):
        assert issue in readme
    assert "schema_version: \"1.0\"" in readme


def test_dataset_card_is_a_labelled_draft() -> None:
    card = _read("DATASET_CARD.draft.md")
    assert "DRAFT - not for upload until #699/#701 approve" in card
    for phrase in ("synthetic=true", "Apache-2.0", "SIMULATED"):
        assert phrase in card


# --------------------------------------------------------------------------------------
# Accessibility basics
# --------------------------------------------------------------------------------------


def test_index_has_accessibility_basics() -> None:
    html = _read("index.html")
    assert re.search(r"<html[^>]*\blang=\"[a-z-]+\"", html)
    assert "<main" in html
    assert re.search(r"<a[^>]*class=\"skip\"[^>]*href=\"#main\"", html)
    assert "aria-live=\"polite\"" in html
    assert re.search(r"<h1>", html)


def test_every_form_control_is_labelled() -> None:
    html = _read("index.html")
    label_targets = set(re.findall(r"<label[^>]*\bfor=\"([^\"]+)\"", html))
    controls = re.findall(r"<(?:input|select|textarea)\b[^>]*>", html)
    assert len(controls) >= 14
    for tag in controls:
        ident = re.search(r"\bid=\"([^\"]+)\"", tag)
        assert ident, f"control without id: {tag}"
        assert ident.group(1) in label_targets or "aria-label=" in tag, f"unlabelled control: {tag}"


def test_css_honours_reduced_motion_and_both_colour_schemes() -> None:
    css = _read("style.css")
    assert "prefers-reduced-motion: reduce" in css
    assert "prefers-color-scheme: dark" in css
    assert ":focus-visible" in css


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    chans = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


TEXT_PAIRS = (
    ("text", "bg"),
    ("text", "surface"),
    ("text", "surface-2"),
    ("muted", "surface"),
    ("muted", "bg"),
    ("muted", "surface-2"),
    ("on-accent", "accent"),
    ("on-danger", "danger"),
    ("banner-text", "banner-bg"),
    ("note-text", "note-bg"),
    ("pass-text", "pass-bg"),
    ("fail-text", "fail-bg"),
    ("abstain-text", "abstain-bg"),
    ("pending-text", "pending-bg"),
    ("accent", "surface"),
)


def test_text_contrast_meets_wcag_aa_in_light_and_dark() -> None:
    css = _read("style.css")
    blocks = re.findall(r":root \{(.*?)\n\s*\}", css, re.S)
    assert len(blocks) == 2, "expected one light and one dark token block"
    for theme, block in zip(("light", "dark"), blocks, strict=True):
        tokens = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block))
        for fg, bg in TEXT_PAIRS:
            ratio = _contrast(tokens[fg], tokens[bg])
            assert ratio >= 4.5, f"{theme}: {fg} on {bg} is {ratio:.2f}:1"
        assert _contrast(tokens["focus"], tokens["surface"]) >= 3, f"{theme}: focus ring too faint"
        assert _contrast(tokens["border"], tokens["surface"]) >= 3, f"{theme}: control border too faint"


# --------------------------------------------------------------------------------------
# Resolver under Node
# --------------------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.timeout(60)
def test_resolver_unit_tests_pass_under_node() -> None:
    node = shutil.which("node")
    assert node is not None
    proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [node, "--test", str(LAB / "resolver.test.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=50,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.timeout(60)
def test_the_page_renders_every_scenario_under_a_stub_dom() -> None:
    node = shutil.which("node")
    assert node is not None
    proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [node, "--test", str(LAB / "ui.test.js")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=50, check=False,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.timeout(60)
def test_replay_eval_tests_and_cli_pass_under_node() -> None:
    node = shutil.which("node")
    assert node is not None
    tests = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [node, "--test", str(LAB / "eval" / "replay.test.js")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=25, check=False,
    )
    assert tests.returncode == 0, tests.stdout + tests.stderr
    first = subprocess.run(  # noqa: S603
        [node, str(LAB / "eval" / "replay.js"), "--json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=25, check=False,
    )
    second = subprocess.run(  # noqa: S603
        [node, str(LAB / "eval" / "replay.js"), "--json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=25, check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert first.stdout == second.stdout, "the replay report is not deterministic"
    report = json.loads(first.stdout)
    assert report["synthetic"] is True
    assert report["false_activations_per_hour"]["value"] is None


# --------------------------------------------------------------------------------------
# Manifest (issue #699): generated, so it must never drift from the files it describes
# --------------------------------------------------------------------------------------


def test_the_manifest_describes_the_data_files_exactly(fixtures: dict[str, Any]) -> None:
    manifest = json.loads(_read("fixtures.manifest.json"))
    assert manifest["schema_version"] == fixtures["schema_version"]
    assert manifest["synthetic"] is True and manifest["consent"] == fixtures["consent"]
    assert manifest["scenarios"] == [s["id"] for s in fixtures["scenarios"]]
    assert manifest["scenario_count"] == len(fixtures["scenarios"])
    assert {f["path"] for f in manifest["files"]} == {"fixtures.js", "fixtures.schema.json"}
    for entry in manifest["files"]:
        data = (LAB / entry["path"]).read_bytes()
        assert b"\r" not in data, f"{entry['path']} must be stored with LF endings (see .gitattributes)"
        assert entry["bytes"] == len(data), f"{entry['path']}: size drifted; regenerate the manifest"
        assert entry["sha256"] == hashlib.sha256(data).hexdigest(), f"{entry['path']}: hash drifted; regenerate"


def test_gitattributes_pins_exactly_the_files_the_manifest_hashes() -> None:
    """Each hashed file and the manifest itself are pinned to LF, and nothing else in the lab is.

    A folder-wide ``examples/hci-hf-lab/** text eol=lf`` pinned ``assets/logo.svg`` to LF
    while ``contrib/icons/yazses.svg`` had no rule, so a ``core.autocrlf=true`` checkout gave
    the two different bytes and ``test_logo_is_the_canonical_icon`` failed.
    """
    manifest = json.loads(_read("fixtures.manifest.json"))
    lines = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    prefix = "examples/hci-hf-lab/"
    want = {prefix + f["path"] for f in manifest["files"]} | {prefix + "fixtures.manifest.json"}
    rules = {line.split()[0]: line for line in lines if line.startswith(prefix)}
    assert set(rules) == want, "pin the hashed files by name, not the whole lab folder"
    for pattern in want:
        assert rules[pattern] == f"{pattern} text eol=lf"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.timeout(60)
def test_the_manifest_generator_agrees_with_the_committed_manifest() -> None:
    node = shutil.which("node")
    assert node is not None
    proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [node, str(LAB / "eval" / "make_manifest.js"), "--check"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=25, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
