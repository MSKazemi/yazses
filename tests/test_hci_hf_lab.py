"""Guards for the synthetic multimodal HCI lab under ``examples/hci-hf-lab/``.

The lab is a static research prototype, not a product feature. What must stay true:

* it is self-contained: no network, no device or microphone API, no external asset;
* its fixtures are synthetic and match the provisional ``0.1-prototype`` schema
  (issue #699 owns the canonical one -- this file must then migrate to it);
* the resolver, run under Node when available, agrees with every fixture;
* the page keeps the accessibility basics it was built with.

``jsonschema`` is not guaranteed to be installed, so the schema check is a small
hand-rolled validator, and the tests below prove it rejects bad input.
"""

from __future__ import annotations

import copy
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
REQUIRED_IDS = {
    "correct_target",
    "low_confidence",
    "stale_sensor",
    "conflicting_modalities",
    "muscle_hold_release",
    "accidental_blink",
    "confirmation_required",
    "emergency_stop",
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
# A small validator for the 0.1-prototype schema. It mirrors fixtures.schema.json for the
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


def validate_fixtures(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if doc.get("schema_version") != "0.1-prototype":
        errors.append("schema_version must be '0.1-prototype'")
    if doc.get("synthetic") is not True:
        errors.append("top-level synthetic must be true")
    if doc.get("license") != "Apache-2.0":
        errors.append("license must be the SPDX id Apache-2.0")
    for key in ("provenance", "generator", "thresholds", "desktop", "intents", "activation_kinds"):
        if key not in doc:
            errors.append(f"missing top-level key {key}")

    for where, value in _confidences(doc):
        if not _is_num(value) or not 0 <= value <= 1:
            errors.append(f"{where}: confidence {value!r} not in [0, 1]")

    window_ids = {w.get("id") for w in doc.get("desktop", {}).get("windows", [])}
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
        decision = sc.get("expected", {}).get("decision")
        if decision not in DECISIONS:
            errors.append(f"{sid}: expected.decision {decision!r} not one of {sorted(DECISIONS)}")
        target = sc.get("expected", {}).get("target")
        if target is not None and target not in window_ids:
            errors.append(f"{sid}: expected.target {target!r} is not a window id")
        if "intended_target" not in sc:
            errors.append(f"{sid}: missing intended_target (use null if none)")
        if "inputs" not in sc:
            errors.append(f"{sid}: missing inputs")

        stamps = [e.get("t_ms") for e in sc.get("timeline", [])]
        if not stamps:
            errors.append(f"{sid}: empty timeline")
        for t in stamps:
            if not _is_int(t) or t < 0:
                errors.append(f"{sid}: malformed timestamp {t!r}")
        ints = [t for t in stamps if _is_int(t)]
        if ints != sorted(ints):
            errors.append(f"{sid}: timeline is not monotonic")
        at = sc.get("decision_at_ms")
        if not _is_int(at) or at < 0 or (ints and at < max(ints)):
            errors.append(f"{sid}: decision_at_ms {at!r} must be an int >= the last event")

        inputs = sc.get("inputs", {})
        for stream, keys in (
            ("gaze", ("age_ms",)),
            ("activation", ("age_ms", "hold_ms")),
        ):
            for k in keys:
                v = inputs.get(stream, {}).get(k)
                if not _is_int(v) or v < 0:
                    errors.append(f"{sid}: inputs.{stream}.{k} {v!r} must be a non-negative int")
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
    assert len(ids) >= 16
    negatives = [s["id"] for s in fixtures["scenarios"] if s["negative_example"]]
    assert len(negatives) >= 2, "issue #699 asks for negative examples, not only successes"


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
    assert "#699" in schema["description"], "the schema must say it is provisional"


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
    assert "0.1-prototype" in readme


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
