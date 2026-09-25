"""The deterministic eye-control task fixtures, and the guard that they stay deterministic.

A result envelope (`test_eye_eval_schema.py`) says what a number *is*. These fixtures say
what was *asked*, and they only earn their place if two machines replay the same thing --
so most of this file checks properties of the generated sequence and geometry rather than
recording what the generator happens to emit today.

That distinction is the point. Comparing the generator's output against the checked-in file
proves byte-stability and nothing else: if the generator were wrong, a characterization test
would faithfully freeze the wrong task as the contract. So the sequence is checked for the
properties it is supposed to have -- balance, no back-to-back repeat, every ring position
visited once, movements that cross the centre, cue gaps wider than any refractory interval,
targets fully on screen and not overlapping -- and *then* checked to be byte-identical.

Two things this file deliberately does not do: infer any threshold or default from a
generated task, and walk the fixture directory without proving the walk can fail. An
iterating guard is trivially green on an empty directory, which is a mistake this repository
has made before, so `test_the_fixture_walk_fails_*` run the same walk against a directory
with nothing in it, one file missing, and one file corrupted.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from yazses.eyeeval import (
    FEATURES,
    FORBIDDEN_FIELD_TOKENS,
    forbidden_field_problems,
    validate_result,
)
from yazses.eyeeval.tasks import (
    BLOCK_KINDS,
    CANVAS_PERMILLE,
    DEFAULT_SEEDS,
    FACE_SWITCH_TASK,
    FIXTURE_FILENAMES,
    FIXTURE_SCHEMA_VERSION,
    GAZE_SCORED_ROUNDS,
    GAZE_TARGET_COUNT,
    GAZE_TASK,
    GEOMETRY_TASKS,
    HEAD_POINTER_TASK,
    MIN_GAZE_PANE_PERMILLE,
    MIN_POINTER_TARGET_PERMILLE,
    POINTER_CONDITIONS,
    POINTER_ISO_ORDER,
    POINTER_PRACTICE_TRIALS,
    POINTER_RING_POSITIONS,
    REQUIRED_TASK_FIELDS,
    SPEAKING_PROMPTS,
    SWITCH_BLOCK_DURATION_S,
    SWITCH_BLOCK_TYPES,
    SWITCH_CUE_COUNT,
    SWITCH_CUE_INTERVAL_MS,
    SWITCH_CUE_JITTER_MS,
    TASK_FEATURES,
    TASK_IDS,
    TASK_OUTCOMES,
    TASK_RECORDS,
    TASK_VERSIONS,
    EyeEvalTaskError,
    check_task,
    dump_task,
    generate_task,
    validate_task,
)

TASK_FIXTURES = Path(__file__).parent / "fixtures" / "eye_eval_tasks"
RESULT_FIXTURES = Path(__file__).parent / "fixtures" / "eye_eval"
TASKS_SOURCE = Path(__file__).resolve().parents[1] / "src" / "yazses" / "eyeeval" / "tasks.py"


def load(root: Path, name: str) -> dict:
    return json.loads((root / name).read_text(encoding="utf-8"))


@pytest.fixture
def gaze() -> dict:
    return generate_task(GAZE_TASK)


@pytest.fixture
def pointer() -> dict:
    return generate_task(HEAD_POINTER_TASK)


@pytest.fixture
def switch() -> dict:
    return generate_task(FACE_SWITCH_TASK)


def scored_blocks(doc: dict) -> list[dict]:
    return [b for b in doc["blocks"] if b["kind"] == "scored"]


# --- the fixture directory, and a walk that can actually fail ------------------------


def fixture_walk_problems(root: Path) -> list[str]:
    """Every problem with the task-fixture directory at `root`, one per line.

    Written to take a root, and to complain about *absence*, for one reason: a check that
    loops over whatever files it finds passes an empty directory without noticing, which
    makes it a guard that can never fail. The tests below run this against an empty
    directory on purpose.
    """
    problems: list[str] = []
    expected = sorted(FIXTURE_FILENAMES.values())
    on_disk = sorted(path.name for path in root.glob("*.json"))
    for name in expected:
        if name not in on_disk:
            problems.append(f"{name}: missing from {root}")
    for name in on_disk:
        if name not in expected:
            problems.append(f"{name}: unexpected file; every fixture needs a task id")
    for name in (n for n in on_disk if n in expected):
        try:
            doc = json.loads((root / name).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{name}: not parseable JSON ({exc.msg})")
            continue
        problems += [f"{name}: {problem}" for problem in validate_task(doc)]
    return problems


def test_the_shipped_task_fixture_set_is_complete_and_valid():
    assert fixture_walk_problems(TASK_FIXTURES) == []


def test_the_fixture_walk_fails_on_an_empty_directory(tmp_path):
    """Guard the guard. Every fixture must be reported missing, by name."""
    problems = fixture_walk_problems(tmp_path)
    assert len(problems) == len(FIXTURE_FILENAMES)
    for name in FIXTURE_FILENAMES.values():
        assert any(p.startswith(f"{name}: missing") for p in problems), problems


@pytest.mark.parametrize("dropped", sorted(FIXTURE_FILENAMES.values()))
def test_the_fixture_walk_fails_when_one_fixture_is_missing(tmp_path, dropped):
    for name in FIXTURE_FILENAMES.values():
        if name != dropped:
            (tmp_path / name).write_text(
                (TASK_FIXTURES / name).read_text(encoding="utf-8"), encoding="utf-8"
            )
    problems = fixture_walk_problems(tmp_path)
    assert problems == [f"{dropped}: missing from {tmp_path}"]


def test_the_fixture_walk_fails_on_a_corrupted_fixture(tmp_path):
    for name in FIXTURE_FILENAMES.values():
        (tmp_path / name).write_text(
            (TASK_FIXTURES / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    doc = load(tmp_path, FIXTURE_FILENAMES[GAZE_TASK])
    doc["scored_trials"] = 39
    (tmp_path / FIXTURE_FILENAMES[GAZE_TASK]).write_text(dump_task(doc), encoding="utf-8")
    assert any("scored_trials" in p for p in fixture_walk_problems(tmp_path))


def test_the_fixture_walk_rejects_an_unparseable_file(tmp_path):
    for name in FIXTURE_FILENAMES.values():
        (tmp_path / name).write_text(
            (TASK_FIXTURES / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (tmp_path / FIXTURE_FILENAMES[FACE_SWITCH_TASK]).write_text("{oh no", encoding="utf-8")
    assert any("not parseable JSON" in p for p in fixture_walk_problems(tmp_path))


def test_the_fixture_walk_rejects_a_stray_file(tmp_path):
    for name in FIXTURE_FILENAMES.values():
        (tmp_path / name).write_text(
            (TASK_FIXTURES / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (tmp_path / "gaze_routing_8_pane.json").write_text("{}", encoding="utf-8")
    assert any("unexpected file" in p for p in fixture_walk_problems(tmp_path))


# --- determinism and byte stability -------------------------------------------------


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_the_generator_reproduces_the_shipped_fixture_byte_for_byte(task_id):
    """The whole claim: the same task, on any machine, down to the bytes.

    If this fails after a deliberate change, regenerate every fixture with the snippet
    below -- run from the repository root -- and bump that task's version in the same
    commit, because a fixture whose contents changed under an unchanged version number is
    the exact silent redefinition the version exists to prevent.

        uv run python - <<'EOF'
        from pathlib import Path
        from yazses.eyeeval.tasks import FIXTURE_FILENAMES, TASK_IDS, dump_task, generate_task
        for task in TASK_IDS:
            target = Path("tests/fixtures/eye_eval_tasks", FIXTURE_FILENAMES[task])
            target.write_text(dump_task(generate_task(task)), encoding="utf-8")
        EOF
    """
    frozen = (TASK_FIXTURES / FIXTURE_FILENAMES[task_id]).read_text(encoding="utf-8")
    assert dump_task(generate_task(task_id)) == frozen


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_two_calls_with_the_same_seed_agree(task_id):
    assert generate_task(task_id) == generate_task(task_id, DEFAULT_SEEDS[task_id])


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_a_different_seed_still_produces_a_valid_task(task_id):
    """A tester may counterbalance differently; every seed must give a legal task."""
    for seed in (0, 1, 7, 123456789):
        other = generate_task(task_id, seed)
        assert validate_task(other) == [], (task_id, seed, validate_task(other))
        assert other["seed"] == seed


def test_a_different_seed_reorders_the_gaze_sequence_but_not_the_panes(gaze):
    other = generate_task(GAZE_TASK, 99)
    assert other["targets"] == gaze["targets"], "pane geometry is fixed, not seeded"
    asked = [t["intended_target_id"] for t in scored_blocks(gaze)[0]["trials"]]
    other_asked = [t["intended_target_id"] for t in scored_blocks(other)[0]["trials"]]
    assert other_asked != asked
    assert sorted(other_asked) == sorted(asked), "a reseed reorders; it never unbalances"


def test_the_generator_does_not_borrow_the_interpreters_randomness():
    """`random`/`secrets` would make the bytes an interpreter detail.

    The module writes SplitMix64 out in full for exactly this reason, and a later edit that
    reached for `random.shuffle` would keep every property test green while quietly making
    the fixture unreproducible on another Python.
    """
    tree = ast.parse(TASKS_SOURCE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported == {"__future__", "json", "typing", "yazses"}, imported


def test_no_float_survives_into_a_fixture():
    """A float would put the bytes at the mercy of whoever formatted them.

    Per-mille integers are the reason a diagonal is `707 // 1000` rather than `1/sqrt(2)`:
    no transcendental function runs, so nothing depends on a platform's libm.
    """

    def floats(node, path="") -> list[str]:
        if isinstance(node, float):
            return [path]
        if isinstance(node, dict):
            return [p for k, v in node.items() for p in floats(v, f"{path}{k}.")]
        if isinstance(node, list):
            return [p for i, v in enumerate(node) for p in floats(v, f"{path}{i}.")]
        return []

    for task_id in TASK_IDS:
        assert floats(load(TASK_FIXTURES, FIXTURE_FILENAMES[task_id])) == [], task_id
        # The generator too, not only the frozen copy: a generator that starts emitting
        # floats must fail here and not merely when somebody regenerates the file.
        for seed in (DEFAULT_SEEDS[task_id], 0, 5):
            assert floats(generate_task(task_id, seed)) == [], (task_id, seed)


# --- the envelope -------------------------------------------------------------------


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_every_task_declares_its_own_version_and_metric_family(task_id):
    doc = generate_task(task_id)
    assert doc["fixture_schema_version"] == FIXTURE_SCHEMA_VERSION
    assert doc["task_version"] == TASK_VERSIONS[task_id]
    assert doc["feature"] == TASK_FEATURES[task_id]
    assert doc["feature"] in FEATURES, "a task must feed a metric family METRICS.md names"
    assert doc["records"] == list(TASK_RECORDS[task_id])
    assert doc["outcomes"] == list(TASK_OUTCOMES[task_id])
    assert doc["privacy"] == {
        "content_source": "generated",
        "raw_media_retained": False,
        "contains_personal_identifiers": False,
    }


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_no_recorded_field_could_hold_private_content(task_id):
    """The privacy argument is structural: there is nowhere to put it."""
    for field in TASK_RECORDS[task_id]:
        for token in FORBIDDEN_FIELD_TOKENS:
            assert token not in field, f"{task_id}.{field} contains {token!r}"
        assert field == field.lower()
    assert len(set(TASK_RECORDS[task_id])) == len(TASK_RECORDS[task_id])


@pytest.mark.parametrize("task_id", GEOMETRY_TASKS)
def test_a_spatial_task_declares_its_coordinate_space(task_id):
    doc = generate_task(task_id)
    assert doc["geometry_units"] == "permille"
    assert doc["canvas_permille"] == {"width": CANVAS_PERMILLE, "height": CANVAS_PERMILLE}


def test_the_face_switch_task_declares_no_geometry(switch):
    """It draws nothing, so a canvas would be a field with no meaning attached."""
    assert "canvas_permille" not in switch
    assert "geometry_units" not in switch


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_every_block_is_practice_or_scored_with_a_unique_id(task_id):
    blocks = generate_task(task_id)["blocks"]
    ids = [block["block_id"] for block in blocks]
    assert len(set(ids)) == len(ids)
    assert {block["kind"] for block in blocks} <= set(BLOCK_KINDS)


# --- gaze: four panes, forty balanced trials ----------------------------------------


def test_the_gaze_task_has_four_large_non_overlapping_panes(gaze):
    panes = gaze["targets"]
    assert len(panes) == GAZE_TARGET_COUNT
    assert [p["target_id"] for p in panes] == [1, 2, 3, 4]
    assert [p["label"] for p in panes] == ["1", "2", "3", "4"]
    for pane in panes:
        assert pane["width"] == pane["height"] >= MIN_GAZE_PANE_PERMILLE
        for centre, edge in (("center_x", "width"), ("center_y", "height")):
            assert 0 <= pane[centre] - pane[edge] // 2
            assert pane[centre] + pane[edge] // 2 <= CANVAS_PERMILLE
    for i, a in enumerate(panes):
        for b in panes[i + 1:]:
            gap_x = abs(a["center_x"] - b["center_x"]) * 2 - a["width"] - b["width"]
            gap_y = abs(a["center_y"] - b["center_y"]) * 2 - a["height"] - b["height"]
            assert gap_x >= 0 or gap_y >= 0, "panes overlap: no unambiguous correct answer"


def test_the_gaze_sequence_is_balanced_and_never_repeats_a_pane(gaze):
    asked = [t["intended_target_id"] for t in scored_blocks(gaze)[0]["trials"]]
    assert len(asked) == GAZE_SCORED_ROUNDS * GAZE_TARGET_COUNT == gaze["scored_trials"]
    assert {i: asked.count(i) for i in range(1, GAZE_TARGET_COUNT + 1)} == {
        i: GAZE_SCORED_ROUNDS for i in range(1, GAZE_TARGET_COUNT + 1)
    }
    assert all(asked[i] != asked[i - 1] for i in range(1, len(asked)))


def test_each_round_of_the_gaze_sequence_visits_every_pane_once(gaze):
    """Balance is structural rather than lucky: it holds for every seed, not this one."""
    for seed in (DEFAULT_SEEDS[GAZE_TASK], 0, 3, 2718281828):
        asked = [
            t["intended_target_id"]
            for t in scored_blocks(generate_task(GAZE_TASK, seed))[0]["trials"]
        ]
        for start in range(0, len(asked), GAZE_TARGET_COUNT):
            round_ = asked[start:start + GAZE_TARGET_COUNT]
            assert sorted(round_) == list(range(1, GAZE_TARGET_COUNT + 1)), (seed, start)
        assert all(asked[i] != asked[i - 1] for i in range(1, len(asked))), seed


def test_the_gaze_practice_block_shows_each_pane_once_and_is_not_scored(gaze):
    practice = [b for b in gaze["blocks"] if b["kind"] == "practice"]
    assert len(practice) == 1
    assert [t["intended_target_id"] for t in practice[0]["trials"]] == [1, 2, 3, 4]
    assert gaze["scored_trials"] == GAZE_SCORED_ROUNDS * GAZE_TARGET_COUNT


def test_the_gaze_task_records_the_intent_and_the_outcome_and_nothing_else(gaze):
    assert "intended_target_id" in gaze["records"]
    assert "outcome" in gaze["records"]
    # Fallback stays distinguishable from a wrong pane: METRICS.md is explicit that
    # collapsing them hides the safer behaviour.
    assert "wrong_target" in gaze["outcomes"]
    assert "fallback_no_route" in gaze["outcomes"]


# --- head pointer: a ring of large generated targets --------------------------------


def test_the_pointer_task_runs_every_declared_condition_once(pointer):
    scored = scored_blocks(pointer)
    assert len(scored) == len(POINTER_CONDITIONS)
    ran = sorted((b["radius_permille"], b["target_width_permille"]) for b in scored)
    assert ran == sorted(POINTER_CONDITIONS)
    assert pointer["scored_trials"] == len(POINTER_CONDITIONS) * POINTER_RING_POSITIONS
    assert [
        (c["radius_permille"], c["target_width_permille"]) for c in pointer["condition_order"]
    ] == [(b["radius_permille"], b["target_width_permille"]) for b in scored]


def test_every_pointer_target_is_large_and_wholly_on_screen(pointer):
    for block in pointer["blocks"]:
        assert len(block["targets"]) == POINTER_RING_POSITIONS
        assert [t["target_id"] for t in block["targets"]] == list(range(POINTER_RING_POSITIONS))
        for target in block["targets"]:
            assert target["width"] == target["height"] == block["target_width_permille"]
            assert target["width"] >= MIN_POINTER_TARGET_PERMILLE
            for centre, edge in (("center_x", "width"), ("center_y", "height")):
                assert target[centre] - target[edge] // 2 >= 0
                assert target[centre] + target[edge] // 2 <= CANVAS_PERMILLE


def test_the_ring_is_centred_and_its_radius_is_the_declared_one(pointer):
    """The axis positions must sit exactly `radius` from the centre, or the amplitude
    recorded against a condition is not the amplitude that was moved."""
    centre = CANVAS_PERMILLE // 2
    for block in pointer["blocks"]:
        radius = block["radius_permille"]
        targets = {t["target_id"]: t for t in block["targets"]}
        assert (targets[0]["center_x"], targets[0]["center_y"]) == (centre + radius, centre)
        assert (targets[2]["center_x"], targets[2]["center_y"]) == (centre, centre + radius)
        assert (targets[4]["center_x"], targets[4]["center_y"]) == (centre - radius, centre)
        assert (targets[6]["center_x"], targets[6]["center_y"]) == (centre, centre - radius)
        # The diagonals are 707/1000 of the radius on each axis -- a shade inside the
        # axis positions, which is what an integer ring costs and is recorded honestly.
        diagonal = targets[1]["center_x"] - centre
        assert diagonal == (radius * 707 + 500) // 1000
        for index in (1, 3, 5, 7):
            assert abs(targets[index]["center_x"] - centre) == diagonal
            assert abs(targets[index]["center_y"] - centre) == diagonal


def test_every_pointer_movement_crosses_the_centre(pointer):
    """The alternating order is the task. A hop to a neighbour would be a short movement
    recorded under the same amplitude condition as a long one."""
    for block in pointer["blocks"]:
        visited = [t["target_id"] for t in block["trials"]]
        assert visited == list(POINTER_ISO_ORDER[:len(visited)])
        assert len(set(visited)) == len(visited)
        for i in range(1, len(visited)):
            step = abs(visited[i] - visited[i - 1]) % POINTER_RING_POSITIONS
            assert min(step, POINTER_RING_POSITIONS - step) >= 3, (block["block_id"], i)


def test_each_pointer_trial_starts_where_the_last_one_ended(pointer):
    centre = CANVAS_PERMILLE // 2
    for block in pointer["blocks"]:
        targets = {t["target_id"]: t for t in block["targets"]}
        assert (block["trials"][0]["start_x"], block["trials"][0]["start_y"]) == (centre, centre)
        for index, trial in enumerate(block["trials"]):
            target = targets[trial["target_id"]]
            assert trial["start_x"] + trial["dx"] == target["center_x"]
            assert trial["start_y"] + trial["dy"] == target["center_y"]
            if index:
                previous = targets[block["trials"][index - 1]["target_id"]]
                assert trial["start_x"] == previous["center_x"]
                assert trial["start_y"] == previous["center_y"]


def test_the_pointer_practice_block_is_short_and_unscored(pointer):
    practice = [b for b in pointer["blocks"] if b["kind"] == "practice"]
    assert len(practice) == 1
    assert len(practice[0]["trials"]) == POINTER_PRACTICE_TRIALS
    assert pointer["scored_trials"] == sum(len(b["trials"]) for b in scored_blocks(pointer))


# --- face switch: deliberate, neutral, speaking --------------------------------------


def test_the_switch_task_runs_all_three_blocks_separately(switch):
    assert [b["block_type"] for b in switch["blocks"]] == list(SWITCH_BLOCK_TYPES)
    assert {"neutral", "deliberate", "speaking"} == set(SWITCH_BLOCK_TYPES)
    for block in switch["blocks"]:
        assert block["duration_s"] == SWITCH_BLOCK_DURATION_S


def test_only_the_deliberate_block_cues_an_activation(switch):
    cued = {b["block_type"]: len(b["cue_times_ms"]) for b in switch["blocks"]}
    assert cued == {"neutral": 0, "deliberate": SWITCH_CUE_COUNT, "speaking": 0}
    assert switch["scored_trials"] == SWITCH_CUE_COUNT


def test_the_cue_times_are_ordered_and_far_enough_apart_to_be_attributable(switch):
    """A gap narrower than the refractory interval would record a correctly suppressed
    bounce as a miss, so the jitter is bounded rather than free."""
    floor = SWITCH_CUE_INTERVAL_MS - 2 * SWITCH_CUE_JITTER_MS
    for seed in (DEFAULT_SEEDS[FACE_SWITCH_TASK], 0, 11, 987654321):
        block = next(
            b for b in generate_task(FACE_SWITCH_TASK, seed)["blocks"]
            if b["block_type"] == "deliberate"
        )
        cues = block["cue_times_ms"]
        assert len(cues) == SWITCH_CUE_COUNT
        assert cues == sorted(cues)
        assert all(0 < cue < block["duration_s"] * 1000 for cue in cues), (seed, cues)
        gaps = [cues[i] - cues[i - 1] for i in range(1, len(cues))]
        assert min(gaps) >= floor, (seed, min(gaps))
        assert len(set(gaps)) > 1, "a metronome would let the tester anticipate"


def test_the_speaking_block_reads_fixed_public_sentences(switch):
    speaking = next(b for b in switch["blocks"] if b["block_type"] == "speaking")
    assert speaking["prompts"] == list(SPEAKING_PROMPTS)
    assert len(SPEAKING_PROMPTS) >= 4
    for prompt in SPEAKING_PROMPTS:
        assert prompt.isascii()
        assert "@" not in prompt and "/" not in prompt
        assert not any(ch.isdigit() for ch in prompt)
    assert all(not b["prompts"] for b in switch["blocks"] if b["block_type"] != "speaking")


def test_the_switch_task_writes_down_what_it_cannot_settle(switch):
    """Fixed block order is a confound. Saying so beats a fixture that looks neutral."""
    assert any("counterbalanced" in note for note in switch["limitations"])
    assert any("threshold" in note for note in switch["limitations"])


# --- validation: each case breaks exactly one thing ---------------------------------


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_a_generated_task_raises_nothing(task_id):
    assert check_task(generate_task(task_id)) is None


@pytest.mark.parametrize("field", REQUIRED_TASK_FIELDS)
def test_a_missing_required_field_is_named(gaze, field):
    gaze.pop(field)
    assert any(p.startswith(f"{field}:") for p in validate_task(gaze)), field


@pytest.mark.parametrize("field", ("geometry_units", "canvas_permille"))
def test_a_spatial_task_without_its_coordinate_space_is_refused(gaze, field):
    gaze.pop(field)
    assert any(p.startswith(f"{field}:") for p in validate_task(gaze))


@pytest.mark.parametrize("bad", ["1", "1.x", "one.two", "", None, 1.0, "v1.0", "1.0.0"])
def test_a_malformed_fixture_version_stops_validation_immediately(gaze, bad):
    """`1.x` is refused on purpose: the minor part is checked, not merely tolerated."""
    gaze["fixture_schema_version"] = bad
    problems = validate_task(gaze)
    assert len(problems) == 1
    assert problems[0].startswith("fixture_schema_version:")


def test_a_newer_major_fixture_version_is_refused_rather_than_replayed(gaze):
    gaze["fixture_schema_version"] = "2.0"
    problems = validate_task(gaze)
    assert len(problems) == 1
    assert "major version 2" in problems[0]


def test_an_unknown_field_is_not_an_error(gaze):
    gaze["instructions_url_added_in_1_4"] = "docs/eye-control.md"
    gaze["targets"][0]["render_hint"] = "outline"
    assert validate_task(gaze) == []


def test_a_task_version_the_module_does_not_implement_is_refused(gaze):
    """The whole reason a task carries a version: replaying 1.1 as 1.0 would change what
    the published rate means without changing its name."""
    gaze["task_version"] = "1.1"
    problems = validate_task(gaze)
    assert any(p.startswith("task_version:") for p in problems), problems


def test_an_unknown_task_id_is_refused(gaze):
    gaze["task_id"] = "gaze_routing_4_panes"
    assert any(p.startswith("task_id:") for p in validate_task(gaze))


def test_a_task_pointed_at_the_wrong_metric_family_is_refused(gaze):
    gaze["feature"] = "head_pointer"
    assert any(p.startswith("feature:") for p in validate_task(gaze))


def test_a_feature_outside_the_metrics_dictionary_is_refused(gaze):
    gaze["feature"] = "eyeballs"
    assert any("is not one of" in p for p in validate_task(gaze) if p.startswith("feature:"))


@pytest.mark.parametrize("token", FORBIDDEN_FIELD_TOKENS)
def test_a_forbidden_field_name_fails_wherever_it_appears(gaze, token):
    gaze["targets"][0][f"pane_{token}"] = "would-be-leak"
    problems = validate_task(gaze)
    assert any(token in p and "forbidden field" in p for p in problems), problems


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_the_shipped_fixtures_trip_no_forbidden_token(task_id):
    doc = load(TASK_FIXTURES, FIXTURE_FILENAMES[task_id])
    assert not [p for p in validate_task(doc) if "forbidden field" in p]


def test_the_forbidden_token_list_is_shared_with_the_result_schema():
    """One list, used by both envelopes. A second copy would drift from the first, and the
    thing that drifted would be the privacy rule."""
    assert forbidden_field_problems({"ok": 1, "nested": [{"deep": 2}]}) == []
    problems = forbidden_field_problems({"provenance": {"machines": [{"hostname": "n1"}]}})
    assert len(problems) == 1
    assert problems[0].startswith("provenance.machines.0.hostname:")
    # `mac_address` must not fire on `machine`, which is why the tokens are spelled out.
    assert forbidden_field_problems({"machine": {"arch": "x86_64"}}) == []


def test_a_task_that_claims_to_capture_the_real_screen_is_refused(gaze):
    gaze["privacy"]["content_source"] = "desktop_capture"
    assert any(p.startswith("privacy.content_source:") for p in validate_task(gaze))


@pytest.mark.parametrize("flag", ("raw_media_retained", "contains_personal_identifiers"))
def test_a_task_may_not_declare_raw_media_or_identifiers(gaze, flag):
    gaze["privacy"][flag] = True
    assert any(p.startswith(f"privacy.{flag}:") for p in validate_task(gaze))


def test_pixels_are_refused_as_a_geometry_unit(gaze):
    gaze["geometry_units"] = "pixels"
    assert any(p.startswith("geometry_units:") for p in validate_task(gaze))


def test_a_float_coordinate_is_refused(gaze):
    gaze["targets"][0]["center_x"] = 255.0
    problems = validate_task(gaze)
    assert any("targets.0.center_x" in p and "whole number" in p for p in problems), problems


def test_a_boolean_is_not_a_coordinate(gaze):
    gaze["targets"][0]["width"] = True
    assert any("targets.0.width" in p for p in validate_task(gaze))


def test_a_target_hanging_off_the_canvas_is_refused(gaze):
    gaze["targets"][3]["center_x"] = CANVAS_PERMILLE - 10
    problems = validate_task(gaze)
    assert any("off-screen" in p for p in problems), problems


def test_an_odd_target_edge_is_refused(gaze):
    gaze["targets"][0]["width"] = 471
    assert any("half-extent" in p for p in validate_task(gaze))


def test_a_gaze_pane_below_the_task_floor_is_refused(gaze):
    for pane in gaze["targets"]:
        pane["width"] = pane["height"] = 100
    problems = validate_task(gaze)
    assert any("below the task's floor" in p for p in problems), problems


def test_overlapping_gaze_panes_are_refused(gaze):
    gaze["targets"][1]["center_x"] = gaze["targets"][0]["center_x"]
    problems = validate_task(gaze)
    assert any("overlap" in p for p in problems), problems


def test_an_unbalanced_gaze_sequence_is_refused(gaze):
    scored_blocks(gaze)[0]["trials"][0]["intended_target_id"] = 2
    problems = validate_task(gaze)
    assert any("unbalanced" in p for p in problems), problems


def test_a_back_to_back_gaze_repeat_is_refused(gaze):
    trials = scored_blocks(gaze)[0]["trials"]
    trials[1]["intended_target_id"] = trials[0]["intended_target_id"]
    problems = validate_task(gaze)
    assert any("back-to-back" in p for p in problems), problems


# An emptied collection is the case every per-item rule passes for free. Each task's
# scored count belongs to its `task_version`, so these three say the count out loud.


def test_an_emptied_gaze_sequence_is_refused(gaze):
    """Balance, no-repeat and round structure are all true of a sequence of nothing."""
    block = scored_blocks(gaze)[0]
    block["trials"] = []
    gaze["scored_trials"] = 0
    problems = validate_task(gaze)
    assert any("scored trials, not 0" in p for p in problems), problems


def test_a_shortened_gaze_sequence_is_refused(gaze):
    block = scored_blocks(gaze)[0]
    block["trials"] = block["trials"][:GAZE_TARGET_COUNT]
    gaze["scored_trials"] = GAZE_TARGET_COUNT
    problems = validate_task(gaze)
    assert any("scored trials, not 4" in p for p in problems), problems


def test_an_emptied_pointer_block_is_refused(pointer):
    block = scored_blocks(pointer)[0]
    block["trials"] = []
    pointer["scored_trials"] -= POINTER_RING_POSITIONS
    problems = validate_task(pointer)
    assert any("ring positions, not 0" in p for p in problems), problems


def test_a_dropped_pointer_condition_is_refused(pointer):
    pointer["blocks"] = pointer["blocks"][:-1]
    pointer["condition_order"] = pointer["condition_order"][:-1]
    pointer["scored_trials"] -= POINTER_RING_POSITIONS
    problems = validate_task(pointer)
    assert any("scored width/radius conditions" in p for p in problems), problems


def test_an_emptied_deliberate_cue_list_is_refused(switch):
    """Ordering and in-window rules hold trivially when nothing is cued at all."""
    block = next(b for b in switch["blocks"] if b["block_type"] == "deliberate")
    block["cue_times_ms"] = []
    switch["scored_trials"] = 0
    problems = validate_task(switch)
    assert any("deliberate activations, not 0" in p for p in problems), problems


def test_a_scored_trial_count_that_does_not_match_the_blocks_is_refused(gaze):
    gaze["scored_trials"] = 41
    problems = validate_task(gaze)
    assert any(p.startswith("scored_trials:") for p in problems), problems


def test_a_duplicate_block_id_is_refused(gaze):
    gaze["blocks"][1]["block_id"] = gaze["blocks"][0]["block_id"]
    assert any("used twice" in p for p in validate_task(gaze))


def test_an_unknown_block_kind_is_refused(gaze):
    gaze["blocks"][0]["kind"] = "warmup"
    assert any(p.startswith("blocks.0.kind:") for p in validate_task(gaze))


def test_a_duplicated_recorded_field_is_refused(gaze):
    gaze["records"] = gaze["records"] + [gaze["records"][0]]
    problems = validate_task(gaze)
    assert any(p.startswith("records:") for p in problems), problems


def test_a_pointer_trial_whose_amplitude_lies_is_refused(pointer):
    pointer["blocks"][1]["trials"][0]["dx"] += 7
    problems = validate_task(pointer)
    assert any("would not be the movement" in p for p in problems), problems


def test_a_pointer_hop_to_a_neighbouring_target_is_refused(pointer):
    block = pointer["blocks"][1]
    block["trials"][1]["target_id"] = 1
    target = block["targets"][1]
    block["trials"][1]["dx"] = target["center_x"] - block["trials"][1]["start_x"]
    block["trials"][1]["dy"] = target["center_y"] - block["trials"][1]["start_y"]
    problems = validate_task(pointer)
    assert any("neighbouring ring position" in p for p in problems), problems


def test_a_ring_position_visited_twice_is_refused(pointer):
    block = pointer["blocks"][1]
    block["trials"][2]["target_id"] = block["trials"][0]["target_id"]
    problems = validate_task(pointer)
    assert any("visited twice" in p for p in problems), problems


def test_a_missing_switch_block_is_refused(switch):
    switch["blocks"] = [b for b in switch["blocks"] if b["block_type"] != "speaking"]
    problems = validate_task(switch)
    assert any(p.startswith("blocks:") for p in problems), problems


def test_a_cue_in_the_neutral_block_is_refused(switch):
    neutral = next(b for b in switch["blocks"] if b["block_type"] == "neutral")
    neutral["cue_times_ms"] = [1000]
    problems = validate_task(switch)
    assert any("cues nothing" in p for p in problems), problems


def test_a_cue_past_the_end_of_the_block_is_refused(switch):
    block = next(b for b in switch["blocks"] if b["block_type"] == "deliberate")
    block["cue_times_ms"][-1] = SWITCH_BLOCK_DURATION_S * 1000 + 1
    problems = validate_task(switch)
    assert any("outside the" in p for p in problems), problems


def test_out_of_order_cues_are_refused(switch):
    block = next(b for b in switch["blocks"] if b["block_type"] == "deliberate")
    block["cue_times_ms"][2], block["cue_times_ms"][3] = (
        block["cue_times_ms"][3],
        block["cue_times_ms"][2],
    )
    problems = validate_task(switch)
    assert any("strictly increase" in p for p in problems), problems


def test_a_tester_supplied_sentence_is_refused(switch):
    speaking = next(b for b in switch["blocks"] if b["block_type"] == "speaking")
    speaking["prompts"][0] = "My address is on the other screen."
    problems = validate_task(switch)
    assert any("fixed public sentences" in p for p in problems), problems


@pytest.mark.parametrize("doc", [[], "task", 7, None])
def test_a_non_object_fixture_is_refused(doc):
    problems = validate_task(doc)
    assert len(problems) == 1
    assert problems[0].startswith("<root>:")


def test_check_task_reports_every_problem_at_once(gaze):
    gaze.pop("description")
    gaze["scored_trials"] = 39
    with pytest.raises(EyeEvalTaskError) as exc:
        check_task(gaze)
    text = str(exc.value)
    assert "description" in text
    assert "scored_trials" in text
    assert "2 eye-control task fixture problem(s)" in text


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_validation_does_not_mutate_the_fixture(task_id):
    doc = generate_task(task_id)
    before = copy.deepcopy(doc)
    validate_task(doc)
    assert doc == before


def test_an_unknown_task_id_cannot_be_generated():
    with pytest.raises(KeyError):
        generate_task("gaze_routing_9_pane")


# --- the task and the result envelope must agree -------------------------------------


def test_the_two_envelopes_do_not_accept_each_other():
    """A task fixture is an input and a result is an output. Mixing them up would put a
    document through the wrong validator and pass nothing useful."""
    for task_id in TASK_IDS:
        assert validate_task(generate_task(task_id)) == []
        assert validate_result(generate_task(task_id)) != []
    for path in sorted(RESULT_FIXTURES.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert validate_result(doc) == [], path.name
        assert validate_task(doc) != [], path.name


def test_every_shipped_result_names_a_task_that_exists_at_the_version_it_ran():
    """The link between the two halves. A result whose task id or version has no fixture
    is a number whose question was never written down."""
    seen = set()
    results = sorted(RESULT_FIXTURES.glob("*.json"))
    assert results, "no result fixtures found -- this check would pass on an empty set"
    for path in results:
        doc = json.loads(path.read_text(encoding="utf-8"))
        task_id = doc["protocol"]["task"]
        assert task_id in TASK_IDS, f"{path.name}: unknown task {task_id!r}"
        assert doc["protocol"]["task_version"] == TASK_VERSIONS[task_id], path.name
        assert doc["feature"]["name"] == TASK_FEATURES[task_id], path.name
        seen.add(task_id)
    assert seen == set(TASK_IDS), f"no example result for {set(TASK_IDS) - seen}"


def test_the_shipped_examples_describe_the_same_nominal_run():
    """The example result for each task reports the trial count its task defines. These
    three files are meant to be read side by side, so a change to one that is not mirrored
    in the other should be noticed rather than discovered by a reader."""
    counts = {
        GAZE_TASK: ("gaze_community_qa.json", lambda m: m["trials"]),
        HEAD_POINTER_TASK: ("head_pointer_community_qa.json", lambda m: m["trials"]),
        FACE_SWITCH_TASK: (
            "face_switch_synthetic.json",
            lambda m: m["blocks"]["deliberate"]["intended_activations"],
        ),
    }
    for task_id, (name, reported) in counts.items():
        doc = json.loads((RESULT_FIXTURES / name).read_text(encoding="utf-8"))
        assert reported(doc["metrics"]) == generate_task(task_id)["scored_trials"], name


def test_the_face_switch_example_block_durations_match_the_task():
    doc = json.loads(
        (RESULT_FIXTURES / "face_switch_synthetic.json").read_text(encoding="utf-8")
    )
    for block in generate_task(FACE_SWITCH_TASK)["blocks"]:
        assert doc["metrics"]["blocks"][block["block_type"]]["duration_s"] == block["duration_s"]
