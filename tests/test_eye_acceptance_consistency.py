"""The acceptance documents for #411 (hardware matrix) and #419 (co-design / fatigue) agree.

Those two issues cannot be closed by code: they need people, cameras and an ethics
determination. What code and documents *can* do is make sure that, when those people arrive,
the matrix they are asked to fill, the metrics they are asked to report, the protocol they are
asked to follow and the wording users read about the feature all say the same thing. Every check
below derives both sides by parsing a committed file or calling the real code; none compares a
hand-written list with a hand-written list.

Each check is a pure function over text, and each is run three ways: on the real files (the
contract), on a deliberately broken copy (so the check demonstrably fails when it should), and on
empty input (so a parser that quietly found nothing is a failure, not a pass).

Nothing here claims that any hardware slot, metric or default is validated. The suite asserts the
opposite where it can: no slot is READY, no outcome file exists, no camera feature is on by
default or called anything but experimental.
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from yazses.config import Config
from yazses.eyeeval import (
    TASK_IDS,
    Provenance,
    build_result,
    generate_task,
    synthetic_records,
    tally,
)
from yazses.system.features import default_enabled_slugs, find_feature

ROOT = Path(__file__).resolve().parent.parent
EYE = ROOT / "design" / "eye-control"
MATRIX = EYE / "VALIDATION_MATRIX.md"
METRICS = EYE / "METRICS.md"
TRACEABILITY = EYE / "TRACEABILITY.md"
REQUIREMENTS = EYE / "CODESIGN_PROTOCOL_REQUIREMENTS.md"
TEMPLATE = EYE / "RESEARCH_PARTICIPANT_TEMPLATE.md"
TEST_PLAN = EYE / "TEST_PLAN.md"
REGISTRY = EYE / "validation-slots.json"
COVERAGE = EYE / "generated" / "validation-coverage.md"
DEVICE_FORM = ROOT / ".github" / "ISSUE_TEMPLATE" / "eye_control_device_report.yml"
GROUNDING_REPORT = ROOT / "tests" / "fixtures" / "grounding_replay_report.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _registry() -> dict[str, Any]:
    return json.loads(_read(REGISTRY))


# ----------------------------------------------------------------------------- parsing


def _section(text: str, heading: str) -> str:
    """The body of the level-2 section called *heading*, or '' when there is none."""
    lines = text.splitlines()
    for start, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            body = []
            for later in lines[start + 1 :]:
                if later.startswith("## "):
                    break
                body.append(later)
            return "\n".join(body)
    return ""


def _tables(text: str) -> list[list[list[str]]]:
    """Every markdown table in *text* as rows of cells, separator rows removed."""
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            current.append([cell.strip() for cell in stripped.strip("|").split("|")])
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return [
        [row for row in table if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in row)]
        for table in tables
    ]


def _first_table(text: str) -> list[list[str]]:
    found = _tables(text)
    return found[0] if found else []


def _ticks(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def _norm(text: str) -> str:
    """Whitespace, emphasis and case folded away, so a quote survives a re-wrap."""
    return re.sub(r"\s+", " ", text.replace("*", "").replace("`", "")).strip().casefold()


# ------------------------------------------------- (a) the matrix and the registry agree

#: Header of the prose "Which test must run where?" table -> the registry's environment
#: vocabulary. A new column that is not here is reported, not skipped.
WHERE_COLUMNS = {
    "Windows": "WIN",
    "macOS": "MAC",
    "GNOME WL": "GNOME",
    "KDE WL": "KDE",
    "X11": "X11",
    "multi-monitor": "HIDPI",
}
#: Words in a cell that make a combination *required* rather than "when supported" or "useful".
REQUIRED_MARKERS = ("A+B", "required", "at least one")
NOT_PERMITTED = ("", "—", "-", "not primary")


def where_table_problems(matrix_text: str, registry: dict[str, Any], coverage_text: str) -> list[str]:
    """Every disagreement between the prose run-where table, the registry and the coverage page."""
    table = _first_table(_section(matrix_text, "Which test must run where?"))
    if len(table) < 2:
        return ["the 'Which test must run where?' table was not found, so nothing was compared."]
    problems: list[str] = []
    columns: dict[int, str] = {}
    for index, name in enumerate(table[0][1:], start=1):
        if name == "CI":
            continue
        if name not in WHERE_COLUMNS:
            problems.append(f"column {name!r} has no registry environment; add it to WHERE_COLUMNS.")
            continue
        columns[index] = WHERE_COLUMNS[name]

    cells: dict[tuple[str, str], str] = {}
    for row in table[1:]:
        match = re.match(r"(T\d)\b", row[0])
        if match is None:
            problems.append(f"row {row[0]!r} does not start with a test-pack id.")
            continue
        for index, env in columns.items():
            cells[(match.group(1), env)] = row[index].replace("*", "").strip() if index < len(row) else ""

    slots = registry.get("slots", [])
    registered = {(s["pack"], s["environment"]) for s in slots if s["environment"] != "ANY"}
    for pack, env in sorted(registered):
        if cells.get((pack, env), "").casefold() in NOT_PERMITTED:
            problems.append(
                f"the registry has a {pack}/{env} cell but the run-where table does not ask for it."
            )
    for pack, env in sorted(registered):
        text = cells.get((pack, env), "")
        if "A+B" in text:
            held = {s["slot"] for s in slots if (s["pack"], s["environment"]) == (pack, env)}
            if not {"A", "B"} <= held:
                problems.append(f"{pack}/{env} says A+B but the registry holds only {sorted(held)}.")

    gaps = _coverage_gaps(coverage_text)
    for (pack, env), text in sorted(cells.items()):
        if any(marker in text for marker in REQUIRED_MARKERS) and (pack, env) not in registered:
            if env not in gaps.get(pack, set()):
                problems.append(
                    f"{pack}/{env} is required by the table, has no registry cell and is not listed "
                    f"on the coverage page as a gap; the absence is undisclosed."
                )
    return problems


def _coverage_gaps(coverage_text: str) -> dict[str, set[str]]:
    table = _first_table(_section(coverage_text, "Combinations with no registered cell"))
    return {row[0]: {e.strip() for e in row[1].split(",")} for row in table[1:] if len(row) >= 2}


def test_the_run_where_table_registry_and_coverage_page_agree():
    assert where_table_problems(_read(MATRIX), _registry(), _read(COVERAGE)) == []


def test_every_cell_the_run_where_table_names_is_registered_or_disclosed_as_a_gap():
    """The derived set is non-empty today: the table asks for cells the registry does not hold."""
    table = _first_table(_section(_read(MATRIX), "Which test must run where?"))
    demanded = {
        (re.match(r"(T\d)", row[0]).group(1), WHERE_COLUMNS[name])  # type: ignore[union-attr]
        for row in table[1:]
        for name, cell in zip(table[0][1:], row[1:], strict=False)
        if name in WHERE_COLUMNS and any(m in cell for m in REQUIRED_MARKERS)
    }
    registered = {(s["pack"], s["environment"]) for s in _registry()["slots"]}
    assert demanded, "the table parsed to no required cell; the check below would be vacuous"
    undisclosed = {
        (pack, env)
        for pack, env in demanded - registered
        if env not in _coverage_gaps(_read(COVERAGE)).get(pack, set())
    }
    assert undisclosed == set()


def test_a_missing_b_slot_is_reported():
    registry = _registry()
    registry["slots"] = [s for s in registry["slots"] if s["id"] != "T0-WIN-B"]
    problems = where_table_problems(_read(MATRIX), registry, _read(COVERAGE))
    assert any("T0/WIN says A+B" in p for p in problems), problems


def test_a_required_cell_the_coverage_page_does_not_list_is_reported():
    problems = where_table_problems(_read(MATRIX), _registry(), "## Combinations with no registered cell\n")
    assert any("undisclosed" in p for p in problems), problems


def test_a_registered_cell_the_table_does_not_ask_for_is_reported():
    registry = _registry()
    extra = {**registry["slots"][0], "id": "T6-WIN-A", "pack": "T6", "environment": "WIN", "issue": None}
    registry["slots"] = [*registry["slots"], extra]
    matrix = _read(MATRIX)
    blanked = re.sub(r"(\| T6 grounding \|[^|]*\|) UIA \|", r"\1 — |", matrix)
    assert blanked != matrix, "the T6 row of the run-where table moved; this test is blind"
    problems = where_table_problems(blanked, registry, _read(COVERAGE))
    assert any("T6/WIN" in p and "does not ask for it" in p for p in problems), problems
    # ...and with the table untouched the same extra cell is permitted.
    assert not any("T6/WIN" in p for p in where_table_problems(matrix, registry, _read(COVERAGE)))


def test_the_where_check_is_not_vacuous_on_empty_input():
    assert where_table_problems("", {"slots": []}, "")
    assert where_table_problems(_read(MATRIX), {"slots": []}, "")


def test_an_unmapped_environment_column_is_reported():
    text = _read(MATRIX).replace("| multi-monitor |", "| Haiku |", 1)
    assert any("Haiku" in p for p in where_table_problems(text, _registry(), _read(COVERAGE)))


# ------------------------------------------------------ (b) the metrics, the code, the docs

_NUMERIC_UNITS = {"count", "fraction", "ms", "s", "per hour", "px"}
_OTHER_UNITS = {"enum", "text", "boolean", "group"}


def unit_from_name(key: str) -> str:
    """The unit a key's own name promises. The unit is part of the name (METRICS.md)."""
    tokens = key.split("_")
    for token, unit in (("ms", "ms"), ("px", "px"), ("s", "s"), ("hour", "per hour")):
        if token in tokens:
            return unit
    if "rate" in tokens or "share" in tokens:
        return "fraction"
    return "count"


_FAKE_MACHINE = Provenance(
    yazses_version="9.9.9",
    git_commit="0123456789ab",
    python_version="3.13.0",
    os_name="ExampleOS",
    os_version="1.2",
    kernel="0.0.0-test",
    arch="x86_64",
    cpu_model="Example CPU 1000",
    logical_cpus=8,
    ram_gb=16.0,
    session_type="headless",
    displays=({"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1.0, "primary": True},),
    packages={"yazses": "9.9.9"},
)


def _synthetic_result(task_id: str) -> dict[str, Any]:
    task = generate_task(task_id)
    return build_result(
        task=task,
        records=synthetic_records(task),
        provenance=_FAKE_MACHINE,
        study_mode="synthetic",
        timestamp="2026-09-25T00:00:00+00:00",
        camera_class="none",
        capture_mode="synthetic_replay",
        records_source="synthetic",
    )


def emitted_keys() -> dict[str, set[str]]:
    """Every key the code can write, by emitter, taken from the code and not from any document."""
    out: dict[str, set[str]] = {}
    for task_id in TASK_IDS:
        out[task_id] = set(tally(generate_task(task_id), []))
    first = _synthetic_result(TASK_IDS[0])
    out["run"] = set(first["run"])
    out["envelope"] = set(first)
    report = json.loads(_read(GROUNDING_REPORT))["strategies"]["semantic_grounding"]
    keys: set[str] = set()
    for name, value in report.items():
        keys |= set(value) if name in ("counts", "rates") else {name}
    out["grounding_replay"] = keys
    return out


def documented_emitted(metrics_text: str) -> dict[str, dict[str, str]]:
    table = _first_table(_section(metrics_text, "Emitted keys"))
    out: dict[str, dict[str, str]] = {}
    for row in table[1:]:
        if len(row) == 4:
            emitter, key = _ticks(row[0]), _ticks(row[1])
            if emitter and key:
                out.setdefault(emitter[0], {})[key[0]] = row[2]
    return out


def documented_defined(metrics_text: str) -> dict[str, str]:
    table = _first_table(_section(metrics_text, "Defined, not yet emitted"))
    return {_ticks(row[0])[0]: row[1] for row in table[1:] if len(row) == 4 and _ticks(row[0])}


def envelope_keys(metrics_text: str) -> set[str]:
    block = re.search(r"```text\n(.*?)```", _section(metrics_text, "Result envelope"), re.DOTALL)
    return set(block.group(1).split()) if block else set()


def protocol_items(matrix_text: str) -> list[tuple[str, str]]:
    """(pack, item) for every bullet a test pack says it will collect or require."""
    heads = re.compile(r"^(Collect|Aggregate|PASS requires|Primary safety outcomes|Collect on [^:]*):\*{0,2}$")
    items: list[tuple[str, str]] = []
    pack: str | None = None
    collecting = False
    for line in matrix_text.splitlines():
        match = re.match(r"^### (T\d) ", line)
        if match:
            pack, collecting = match.group(1), False
        elif line.startswith("## "):
            pack, collecting = None, False
        elif pack and heads.match(line.strip()):
            collecting = True
        elif collecting and line.startswith("- "):
            items.append((pack, line[2:].strip().replace("**", "").rstrip(";.").strip()))
        elif collecting:
            collecting = False
    return items


def coverage_rows(metrics_text: str) -> list[tuple[str, str, list[str], list[str]]]:
    table = _first_table(_section(metrics_text, "Protocol coverage"))
    return [
        (row[0], row[1].strip(), _ticks(row[2]), _ticks(row[3])) for row in table[1:] if len(row) == 4
    ]


def metrics_problems(metrics_text: str, matrix_text: str, emitted: dict[str, set[str]]) -> list[str]:
    problems: list[str] = []
    documented = documented_emitted(metrics_text)
    if not documented:
        return ["the 'Emitted keys' table was not found, so nothing was compared."]
    for emitter, code_keys in emitted.items():
        if emitter == "envelope":
            continue
        listed = documented.get(emitter, {})
        for key in sorted(code_keys - set(listed)):
            problems.append(f"{emitter}: the code can emit {key!r} but METRICS.md does not list it.")
        for key in sorted(set(listed) - code_keys):
            problems.append(f"{emitter}: METRICS.md lists {key!r} but the code does not emit it.")
    for emitter in sorted(set(documented) - set(emitted)):
        problems.append(f"METRICS.md lists an emitter {emitter!r} that the code does not have.")
    for emitter, keys in documented.items():
        for key, unit in keys.items():
            if unit not in _NUMERIC_UNITS | _OTHER_UNITS:
                problems.append(f"{emitter}.{key}: unit {unit!r} is not in the vocabulary.")
            elif unit in _NUMERIC_UNITS and unit != unit_from_name(key):
                problems.append(f"{emitter}.{key}: documented unit {unit!r} but the name says {unit_from_name(key)!r}.")

    if envelope_keys(metrics_text) != emitted.get("envelope", set()):
        problems.append(
            f"the 'Result envelope' list {sorted(envelope_keys(metrics_text))} differs from the "
            f"top-level keys the runner writes {sorted(emitted.get('envelope', set()))}."
        )

    defined = documented_defined(metrics_text)
    if not defined:
        problems.append("the 'Defined, not yet emitted' table was not found.")
    every_emitted = set().union(*emitted.values())
    for key, unit in defined.items():
        if key in every_emitted:
            problems.append(f"{key!r} is now emitted; move it out of 'Defined, not yet emitted'.")
        if unit not in _NUMERIC_UNITS | _OTHER_UNITS:
            problems.append(f"defined key {key!r}: unit {unit!r} is not in the vocabulary.")
        elif unit in _NUMERIC_UNITS and unit != unit_from_name(key):
            problems.append(f"defined key {key!r}: documented unit {unit!r} but the name says {unit_from_name(key)!r}.")

    wanted = protocol_items(matrix_text)
    have = coverage_rows(metrics_text)
    if not wanted:
        problems.append("no protocol items were parsed from VALIDATION_MATRIX.md.")
    if not have:
        problems.append("the 'Protocol coverage' table was not found.")
    have_pairs = [(pack, item) for pack, item, _, _ in have]
    for pair in wanted:
        if pair not in have_pairs:
            problems.append(f"{pair[0]} says it will collect {pair[1]!r}; METRICS.md 'Protocol coverage' has no row for it.")
    for pair in have_pairs:
        if pair not in wanted:
            problems.append(f"'Protocol coverage' has a row {pair} that VALIDATION_MATRIX.md no longer asks for.")
    for pack, item, emits, defines in have:
        if not emits and not defines:
            problems.append(f"{pack} {item!r} maps to no key at all.")
        for key in emits:
            if key not in every_emitted:
                problems.append(f"{pack} {item!r}: {key!r} is listed as emitted but the code does not emit it.")
        for key in defines:
            if key not in defined:
                problems.append(f"{pack} {item!r}: {key!r} is not in 'Defined, not yet emitted'.")
    return problems


def test_the_emitted_keys_are_documented_with_their_units_and_the_protocol_maps_onto_them():
    assert metrics_problems(_read(METRICS), _read(MATRIX), emitted_keys()) == []


def test_the_emitted_key_derivation_is_not_empty():
    emitted = emitted_keys()
    assert {"gaze_routing_4_pane", "head_pointer_generated_targets", "face_switch_blocks"} <= set(emitted)
    assert all(emitted[task] for task in TASK_IDS)
    assert "verdict" in emitted["run"] and "metrics" in emitted["envelope"]
    assert "wrong_target_rate" in emitted["grounding_replay"]


def test_a_key_the_code_emits_but_the_docs_omit_is_reported():
    emitted = emitted_keys()
    emitted["face_switch_blocks"] = emitted["face_switch_blocks"] | {"secret_new_metric"}
    problems = metrics_problems(_read(METRICS), _read(MATRIX), emitted)
    assert any("secret_new_metric" in p and "does not list" in p for p in problems), problems


def test_a_key_the_docs_list_but_the_code_dropped_is_reported():
    emitted = emitted_keys()
    emitted["face_switch_blocks"] = emitted["face_switch_blocks"] - {"detection_rate"}
    problems = metrics_problems(_read(METRICS), _read(MATRIX), emitted)
    assert any("detection_rate" in p and "does not emit" in p for p in problems), problems


def test_a_defined_only_key_that_becomes_emitted_must_leave_the_gap_table():
    emitted = emitted_keys()
    emitted["head_pointer_generated_targets"] = emitted["head_pointer_generated_targets"] | {"exposure_s"}
    problems = metrics_problems(_read(METRICS), _read(MATRIX), emitted)
    assert any("exposure_s" in p and "now emitted" in p for p in problems), problems


def test_a_unit_that_contradicts_the_name_is_reported():
    text = _read(METRICS).replace(
        "| `movement_time_ms_p50` | ms |", "| `movement_time_ms_p50` | s |", 1
    )
    assert text != _read(METRICS)
    problems = metrics_problems(text, _read(MATRIX), emitted_keys())
    assert any("movement_time_ms_p50" in p and "name says 'ms'" in p for p in problems), problems


def test_a_new_protocol_item_without_a_coverage_row_is_reported():
    text = _read(MATRIX).replace("- target success;", "- target success;\n- pupil dilation;", 1)
    problems = metrics_problems(_read(METRICS), text, emitted_keys())
    assert any("pupil dilation" in p for p in problems), problems


def test_a_coverage_row_pointing_at_an_unknown_key_is_reported():
    text = _read(METRICS).replace("| T2 | target success | `hit` |", "| T2 | target success | `hits_total` |", 1)
    assert text != _read(METRICS)
    problems = metrics_problems(text, _read(MATRIX), emitted_keys())
    assert any("hits_total" in p for p in problems), problems


def test_the_metrics_check_is_not_vacuous_on_empty_input():
    assert metrics_problems("", "", emitted_keys())
    assert metrics_problems(_read(METRICS), "", emitted_keys())
    assert protocol_items("") == [] and coverage_rows("") == [] and documented_emitted("") == {}


def test_the_protocol_items_parser_found_every_pack():
    packs = {pack for pack, _ in protocol_items(_read(MATRIX))}
    assert packs == {f"T{n}" for n in range(8)}


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_every_emitted_value_has_the_unit_its_name_promises(task_id):
    """The documented unit is checked against the name above; this checks the values obey the name."""
    metrics = _synthetic_result(task_id)["metrics"]
    assert metrics
    for key, value in metrics.items():
        if isinstance(value, dict):  # an explicit missing marker, never a zero
            assert value["value"] is None and value["reason"]
            continue
        unit = unit_from_name(key)
        assert isinstance(value, (int, float)) and not isinstance(value, bool), key
        assert value >= 0, key
        if unit == "fraction":
            assert value <= 1, key
        if unit == "count":
            assert float(value).is_integer(), key


# --------------------------------------- #411 report fields have somewhere to be written

#: TEST_PLAN "Layer E" report field -> the id of the public hardware-report form field that
#: carries it. The mapping is the one hand-written fact here; the checks make it complete.
FORM_FIELD = {
    "OS/session": "os",
    "camera/tracker": "camera",
    "lighting": "lighting",
    "glasses": "glasses",
    "display": "display",
    "viewing distance": "distance",
    "feature/config": "config",
    "session duration": "duration",
    "failures": "failures",
    "CPU/FPS": "metrics",
    "privacy check": "privacy",
}


def form_problems(test_plan_text: str, form: dict[str, Any]) -> list[str]:
    tables = [t for t in _tables(test_plan_text) if t and t[0][:1] == ["Field"]]
    if not tables:
        return ["the TEST_PLAN 'Field | Examples' table was not found."]
    fields = {row[0] for row in tables[0][1:]}
    problems = [f"TEST_PLAN asks for {f!r}; FORM_FIELD does not map it." for f in sorted(fields - set(FORM_FIELD))]
    problems += [f"FORM_FIELD maps {f!r}; TEST_PLAN no longer asks for it." for f in sorted(set(FORM_FIELD) - fields)]
    items = {item["id"]: item for item in form.get("body", []) if isinstance(item, dict) and "id" in item}
    for field, form_id in FORM_FIELD.items():
        if form_id not in items:
            problems.append(f"{field!r} has no form field with id {form_id!r}.")
    if "CPU/FPS" in fields:
        description = str(items.get("metrics", {}).get("attributes", {}).get("description", ""))
        if "CPU/FPS" not in description:
            problems.append("CPU/FPS has no dedicated field, so the 'metrics' field must at least ask for it.")
    return problems


def _form() -> dict[str, Any]:
    return yaml.safe_load(_read(DEVICE_FORM))


def test_every_field_the_test_plan_asks_a_tester_to_report_has_a_form_field():
    assert form_problems(_read(TEST_PLAN), _form()) == []


def test_a_field_dropped_from_the_form_is_reported():
    form = _form()
    form["body"] = [i for i in form["body"] if i.get("id") != "distance"]
    assert any("viewing distance" in p for p in form_problems(_read(TEST_PLAN), form))


def test_a_field_added_to_the_test_plan_is_reported():
    text = _read(TEST_PLAN).replace("| privacy check |", "| battery level | 80% |\n| privacy check |", 1)
    assert any("battery level" in p for p in form_problems(text, _form()))


def test_the_form_check_is_not_vacuous_on_empty_input():
    assert form_problems("", {})
    assert form_problems(_read(TEST_PLAN), {})


def test_the_public_report_form_has_no_comfort_or_fatigue_field_and_the_requirements_say_so():
    """#419 asks for a before/after comfort rating. If the form gains one, move element 1 of
    CODESIGN_PROTOCOL_REQUIREMENTS.md from 'must still specify' to 'provided today'."""
    labels = [
        f"{item.get('id', '')} {item.get('attributes', {}).get('label', '')}".casefold()
        for item in _form()["body"]
        if isinstance(item, dict)
    ]
    assert labels
    assert not [label for label in labels if "fatigue" in label or "comfort" in label]


# ------------------------------------------- #419 the protocol requirements are honest

REQUIRED_ELEMENTS = (
    "Measures",
    "Session length and exposure",
    "Rest rules",
    "Stopping rules",
    "Adverse-event handling",
    "Accessibility of the protocol itself",
    "What consent covers",
)
#: A number with a unit would be a protocol decision made by a requirements file.
_NUMBER_WITH_UNIT = re.compile(r"\b\d+(?:\.\d+)?\s*(?:min(?:ute)?s?|seconds?|secs?|ms|hours?|hrs?|%)\b", re.I)


def requirements_problems(text: str, others: dict[str, str]) -> list[str]:
    table = _first_table(_section(text, "Element register"))
    if len(table) < 2:
        return ["the 'Element register' table was not found."]
    problems: list[str] = []
    rows = {row[1]: row for row in table[1:] if len(row) == 5}
    for element in REQUIRED_ELEMENTS:
        if element not in rows:
            problems.append(f"required protocol element {element!r} is missing from the register.")
    for element, row in rows.items():
        provided, absent, must = _ticks(row[2]), _ticks(row[3]), row[4]
        if not must.strip():
            problems.append(f"{element}: nothing is said about what the frozen protocol must specify.")
        if not provided and not absent:
            problems.append(f"{element}: neither a provided quote nor an absence is recorded.")
        for span in provided:
            if " :: " not in span:
                problems.append(f"{element}: {span!r} is not 'file :: phrase'.")
                continue
            name, phrase = span.split(" :: ", 1)
            source = others.get(name)
            if source is None:
                problems.append(f"{element}: {name!r} is not a document in design/eye-control.")
            elif _norm(phrase) not in _norm(source):
                problems.append(f"{element}: {name} no longer contains {phrase!r}.")
        for span in absent:
            if not span.startswith("absent :: "):
                problems.append(f"{element}: {span!r} is not 'absent :: term'.")
                continue
            term = _norm(span.removeprefix("absent :: ")).replace("-", " ")
            for name, source in others.items():
                if term in _norm(source).replace("-", " "):
                    problems.append(
                        f"{element}: {name} now contains {term!r}; the register says it is absent. "
                        f"Move it to 'Provided today'."
                    )
    stop = _section(text, "Proposed minimum facilitator-must-stop conditions")
    if len(re.findall(r"(?m)^\d+\. ", stop)) < 5:
        problems.append("the must-stop list has fewer than five conditions.")
    prose = re.sub(r"`[^`]*`", "", text)
    problems += [f"the requirements file sets a number: {m.group(0)!r}." for m in _NUMBER_WITH_UNIT.finditer(prose)]
    return problems


def _design_texts(exclude: Path | None = None) -> dict[str, str]:
    return {p.name: _read(p) for p in sorted(EYE.glob("*.md")) if p != exclude}


def test_the_protocol_requirements_quote_text_that_exists_and_name_only_gaps_that_exist():
    assert requirements_problems(_read(REQUIREMENTS), _design_texts(exclude=REQUIREMENTS)) == []


def test_a_quote_that_was_edited_away_is_reported():
    others = _design_texts(exclude=REQUIREMENTS)
    others["METRICS.md"] = others["METRICS.md"].replace("fatigue/change over session", "")
    problems = requirements_problems(_read(REQUIREMENTS), others)
    assert any("no longer contains" in p for p in problems), problems


def test_an_absence_that_stopped_being_true_is_reported():
    others = _design_texts(exclude=REQUIREMENTS)
    others["GOVERNANCE.md"] += "\nAn adverse event is reported to the institution.\n"
    problems = requirements_problems(_read(REQUIREMENTS), others)
    assert any("'adverse'" in p and "Move it" in p for p in problems), problems


def test_a_missing_required_element_is_reported():
    text = _read(REQUIREMENTS)
    lines = [line for line in text.splitlines() if "| Rest rules |" not in line]
    problems = requirements_problems("\n".join(lines), _design_texts(exclude=REQUIREMENTS))
    assert any("Rest rules" in p for p in problems), problems


def test_a_number_written_into_the_requirements_is_reported():
    text = _read(REQUIREMENTS).replace("`<N, set by the protocol>`", "3 minutes")
    problems = requirements_problems(text, _design_texts(exclude=REQUIREMENTS))
    assert any("sets a number" in p for p in problems), problems


def test_the_requirements_check_is_not_vacuous_on_empty_input():
    assert requirements_problems("", {})
    assert requirements_problems(_read(REQUIREMENTS), {})


def test_the_participant_template_carries_no_protocol_id_and_no_ethics_reference():
    """The template is a template. A filled-in protocol id or approval reference in it would be
    an invented fact; every such line must still be a `<PLACEHOLDER>`."""
    labels = (
        "Protocol ID/version:",
        "Responsible institution:",
        "Principal/responsible researcher:",
        "Ethics/review determination:",
        "Private contact for questions/withdrawal:",
        "Data retention period:",
        "Study software commit/release:",
    )
    lines = _read(TEMPLATE).splitlines()
    for label in labels:
        found = [line for line in lines if line.startswith(label)]
        assert len(found) == 1, f"{label!r} is not on exactly one line"
        assert re.search(r"`<[^`>]+>`", found[0]), f"{found[0]!r} is not a placeholder"


def test_a_filled_in_protocol_id_would_be_caught():
    line = "Protocol ID/version: `EYE-2026-01 v1`"
    assert not re.search(r"`<[^`>]+>`", line)


def test_no_committed_design_document_names_an_approved_protocol():
    """No document in the eye-control tree claims an approval or a protocol number."""
    pattern = re.compile(
        r"\b(?:approved by|ethics approval (?:number|no\.?|ref)|IRB (?:number|no\.?|protocol)|protocol (?:number|no\.?)"
        r"|protocol id:?\s*[A-Z0-9][A-Z0-9-]{3,})\b",
        re.I,
    )
    hits = [
        f"{name}: {m.group(0)!r}"
        for name, text in _design_texts().items()
        for m in pattern.finditer(text)
        if "final approved" not in text[max(0, m.start() - 20) : m.end() + 20]
    ]
    assert hits == [], hits


# ------------------------------- (e) the acceptance criteria are linked, not just listed

_TRACE_HEADING = "Acceptance traceability — #411 and #419"


def traceability_problems(text: str, registry: dict[str, Any], root: Path = ROOT) -> list[str]:
    table = _first_table(_section(text, _TRACE_HEADING))
    if len(table) < 2:
        return ["the acceptance traceability table was not found."]
    problems: list[str] = []
    slot_ids = [s["id"] for s in registry.get("slots", [])]
    claimed: set[str] = set()
    seen: set[str] = set()
    for row in table[1:]:
        if len(row) != 6:
            problems.append(f"row {row[:1]} has {len(row)} cells, expected 6.")
            continue
        row_id, _item, issue, slots, test, person = row
        if row_id in seen:
            problems.append(f"{row_id}: appears twice.")
        seen.add(row_id)
        if not re.fullmatch(r"#\d+", issue):
            problems.append(f"{row_id}: issue {issue!r} is not '#N'.")
        elif {"H": "#411", "A": "#419"}.get(row_id[:1]) != issue:
            problems.append(f"{row_id}: id prefix and issue {issue} disagree.")
        if person not in ("yes", "no"):
            problems.append(f"{row_id}: 'needs a person' must be yes or no, got {person!r}.")
        if slots != "—":
            for glob in _ticks(slots):
                matched = fnmatch.filter(slot_ids, glob)
                if not matched:
                    problems.append(f"{row_id}: slot pattern {glob!r} matches no registry cell.")
                claimed.update(matched)
        if test == "—":
            if person != "yes":
                problems.append(f"{row_id}: has no test and does not say a person is needed.")
            continue
        spans = _ticks(test)
        if len(spans) != 1 or "::" not in spans[0]:
            problems.append(f"{row_id}: test {test!r} is not a single `path::name`.")
            continue
        path, name = spans[0].split("::", 1)
        file = root / path
        if not file.is_file():
            problems.append(f"{row_id}: test file {path} does not exist.")
        elif not re.search(rf"(?m)^\s*(?:async\s+)?def {re.escape(name)}\(", file.read_text(encoding="utf-8")):
            problems.append(f"{row_id}: {path} defines no function {name}.")
    for slot in sorted(set(slot_ids) - claimed):
        problems.append(f"registry cell {slot} is linked from no acceptance row.")
    if not any(r.startswith("H") for r in seen) or not any(r.startswith("A") for r in seen):
        problems.append("both #411 (H) and #419 (A) need at least one acceptance row.")
    return problems


def test_every_acceptance_criterion_is_linked_to_an_issue_a_slot_and_a_test_that_exist():
    assert traceability_problems(_read(TRACEABILITY), _registry()) == []


def test_a_test_name_that_does_not_exist_is_reported():
    text = _read(TRACEABILITY).replace(
        "test_a_stale_sample_never_moves_the_pointer_again", "test_a_name_nobody_wrote", 1
    )
    assert any("test_a_name_nobody_wrote" in p for p in traceability_problems(text, _registry()))


def test_a_slot_pattern_that_matches_nothing_is_reported():
    text = _read(TRACEABILITY).replace("`T5-*`", "`T9-*`", 1)
    assert any("T9-*" in p for p in traceability_problems(text, _registry()))


def test_a_registry_cell_no_row_links_is_reported():
    registry = _registry()
    registry["slots"] = [*registry["slots"], {**registry["slots"][0], "id": "T7-WIN-A", "pack": "T7", "issue": None}]
    assert any("T7-WIN-A" in p for p in traceability_problems(_read(TRACEABILITY), registry))


def test_a_row_with_no_issue_is_reported():
    text = _read(TRACEABILITY).replace("| H3 | Head-Pointer overshoot and accidental clicks | #411 |", "| H3 | Head-Pointer overshoot and accidental clicks | |", 1)
    assert any("H3" in p and "not '#N'" in p for p in traceability_problems(text, _registry()))


def test_the_traceability_check_is_not_vacuous_on_empty_input():
    assert traceability_problems("", {"slots": []})
    assert traceability_problems(_read(TRACEABILITY), {"slots": []}), "every pattern must match something"


# ------------------------------------ (d) nothing recommends a hands-free default yet

#: The camera features of the eye / hands-free programme. GOVERNANCE.md calls every one of them
#: EXPERIMENTAL until Gate 7; docs/capability-matrix.md says so to users.
CAMERA_FEATURES = ("gaze", "facegesture", "headpointer", "gesture")


def test_every_camera_feature_is_described_as_experimental_where_the_registry_describes_it():
    config = Config()
    for slug in CAMERA_FEATURES:
        feature = find_feature(config, slug)
        assert feature is not None, slug
        text = f"{feature.name} {feature.note} {feature.why} {feature.tier_label}".casefold()
        assert "experimental" in text, f"{slug} is described without the word 'experimental': {feature.why!r}"
        # Checked on the runtime string: the source wraps it across adjacent literals, so a
        # line-oriented scan of features.py would never see this phrase.
        assert "fully hands-free" not in text, f"{slug} promises a fully hands-free desktop: {feature.why!r}"


def test_no_camera_feature_is_on_in_a_default_install():
    assert not set(default_enabled_slugs()) & {*CAMERA_FEATURES, "modality"}
    config = Config()
    assert config.gaze.enabled is False
    assert config.facegesture.enabled is False
    assert config.headpointer.enabled is False
    assert config.gesture.enabled is False
    assert config.handsfree.enabled is False
    assert config.handsfree_safety.enabled is False


_HEAD_POINTER = re.compile(r"head[- ]?pointer|head pose|tilting your head", re.I)


def overclaiming_lines(text: str) -> list[str]:
    """Lines that pair the Head-Pointer with the unqualified promise of a 'fully hands-free' desktop."""
    return [
        line.strip()
        for line in text.splitlines()
        if re.search(r"fully hands-free", line, re.I) and _HEAD_POINTER.search(line)
    ]


def _english_docs() -> list[Path]:
    return sorted(
        path
        for path in (ROOT / "docs").rglob("*.md")
        if not re.match(r"^[a-z]{2}(?:-[A-Za-z]+)?$", path.relative_to(ROOT / "docs").parts[0])
    )


def test_no_user_facing_text_promises_a_fully_hands_free_desktop_from_the_head_pointer():
    paths = [*_english_docs(), ROOT / "README.md"]
    assert len(paths) > 20, "the docs tree was not found, so nothing was scanned"
    hits = [f"{p.relative_to(ROOT).as_posix()}: {line}" for p in paths for line in overclaiming_lines(_read(p))]
    assert hits == [], hits


def test_the_overclaim_scan_would_catch_the_wording_it_replaced():
    assert overclaiming_lines("| **Head-Pointer** | `headpointer` | Move + click; fully hands-free with voice. |")
    assert overclaiming_lines("pair with voice for a fully hands-free desktop. Tilting your head")
    assert not overclaiming_lines("EMG trigger for fully hands-free use")
    assert overclaiming_lines("") == []


def test_the_preset_and_the_hands_free_config_say_their_values_are_provisional():
    """The surfaces that turn the preset on carry the caveat; this pins the config reference."""
    configuration = _read(ROOT / "docs" / "configuration.md")
    section = _section(configuration, "`[handsfree]`")
    assert section, "the [handsfree] section of the configuration reference was not found"
    assert "provisional" in section and "none validated with users" in section
