"""The three task fixtures, driven through the real code they were written to evaluate.

`test_eye_eval_tasks.py` checks that a fixture is well formed; `test_eye_eval_runner.py`
checks that outcomes are counted. Neither runs a task against an implementation, so neither
can say that a fixture would *notice a wrong one*. A fixture that every implementation
passes is a fixture that measures nothing, and that is the hazard here: the runner's own
synthetic records are all-success by design, so a green tally over them cannot distinguish a
working feature from a broken one.

So each task family below is replayed through the repository's real pure code, with the
expected answer **derived from the task document** (the panes, the ring, the cue times),
never copied from a number:

* gaze    -> `gaze.zones` (`window_at_point`, `grid_zone`): aim at the centre of the pane a
  trial asks for; the pane that comes back is the answer;
* pointer -> `headpointer.pointer` (`pose_to_cursor`, `limit_velocity`, `elapsed_s`,
  `DwellClicker`): a closed-loop simulated head steers from each trial's recorded start to
  its target; a click inside the target's rectangle is a hit;
* switch  -> `eyeeval.switch_replay` (the real `GestureSwitch`): a numeric trace is laid out
  from the deliberate block's cue times and the speaking block's prompts.

Each family then runs a deliberately wrong implementation (a mutant) and the test requires a
*different* answer. A mutant that survives would mean the fixture cannot tell right from
wrong, which is the one thing a fixture is for.

## What this does not claim

Nothing here measures a person, a camera or a product threshold. The simulated head, the
simulated gaze point and the simulated trace are inventions chosen so that the right answer
is knowable from the task alone; that is what makes them a known-answer test of the
*harness and the fixtures*, and nothing at all about how well YazSes works for anyone. The
gaze fixture's panes are equal and disjoint, so it cannot distinguish `window_at_point`'s
smallest-window tie-break from any other rule -- that is a grounding question with its own
fixtures (`tests/test_grounding_replay.py`), not something this task can speak to.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from typing import Any

import pytest

from yazses.eyeeval import (
    DEFAULT_SEEDS,
    FACE_SWITCH_TASK,
    GAZE_TASK,
    HEAD_POINTER_TASK,
    check_records,
    completeness_verdict,
    generate_task,
    tally,
)
from yazses.eyeeval.switch_replay import SwitchConfig, replay_trace
from yazses.eyeeval.switch_trace import check_trace
from yazses.eyeeval.tasks import (
    CANVAS_PERMILLE,
    FIXTURE_FILENAMES,
    SPEAKING_PROMPTS,
    TASK_IDS,
    dump_task,
    validate_task,
)
from yazses.facegesture.detector import GESTURES
from yazses.gaze.zones import grid_zone, window_at_point
from yazses.headpointer.pointer import (
    DwellClicker,
    PointerCalib,
    elapsed_s,
    limit_velocity,
    pose_to_cursor,
)

#: A reseed must not change what is asked of the implementation, only its order.
SEEDS = (None, 0, 1, 20261015)


def _seed_id(seed: int | None) -> str:
    return "default" if seed is None else str(seed)


def scored_blocks(task: dict[str, Any]) -> list[dict[str, Any]]:
    return [b for b in task["blocks"] if b["kind"] == "scored"]


# =========================================================================================
# gaze: the pane a trial asks for is the pane the real resolver returns
# =========================================================================================

Resolver = Callable[[float, float], "int | None"]


def pane_windows(task: dict[str, Any]) -> list[tuple[int, float, float, float, float]]:
    """The task's panes as `window_at_point` wants them: `(id, left, top, width, height)`."""
    return [
        (
            p["target_id"],
            p["center_x"] - p["width"] / 2,
            p["center_y"] - p["height"] / 2,
            p["width"],
            p["height"],
        )
        for p in task["targets"]
    ]


def real_window_resolver(task: dict[str, Any]) -> Resolver:
    windows = pane_windows(task)
    return lambda x, y: window_at_point(x, y, windows)


def real_grid_resolver(_task: dict[str, Any]) -> Resolver:
    """Panes are numbered row-major from 1, so the grid zone plus one is the pane id."""
    return lambda x, y: grid_zone(x, y, CANVAS_PERMILLE, CANVAS_PERMILLE, 2, 2) + 1


def _transposed(_task: dict[str, Any]) -> Resolver:
    """Column-major numbering: the classic row/column mix-up."""
    return lambda x, y: grid_zone(y, x, CANVAS_PERMILLE, CANVAS_PERMILLE, 2, 2) + 1


def _mirrored(_task: dict[str, Any]) -> Resolver:
    return lambda x, y: grid_zone(CANVAS_PERMILLE - x, y, CANVAS_PERMILLE, CANVAS_PERMILLE, 2, 2) + 1


def _zero_based(_task: dict[str, Any]) -> Resolver:
    """Pane numbers from 0: an off-by-one between the prompt and the answer."""
    return lambda x, y: grid_zone(x, y, CANVAS_PERMILLE, CANVAS_PERMILLE, 2, 2)


GAZE_MUTANTS = {"transposed": _transposed, "mirrored": _mirrored, "zero_based": _zero_based}


def run_gaze(task: dict[str, Any], resolver: Resolver) -> list[dict[str, Any]]:
    """One record per scored trial: aim at the asked-for pane's centre, record what resolved."""
    centres = {p["target_id"]: (p["center_x"], p["center_y"]) for p in task["targets"]}
    records = []
    for block in scored_blocks(task):
        for trial in block["trials"]:
            intended = trial["intended_target_id"]
            got = resolver(*centres[intended])
            outcome = (
                "fallback_no_route" if got is None else "correct" if got == intended else "wrong_target"
            )
            records.append(
                {
                    "trial_index": trial["trial_index"],
                    "intended_target_id": intended,
                    "outcome": outcome,
                }
            )
    return records


@pytest.mark.parametrize("seed", SEEDS, ids=_seed_id)
@pytest.mark.parametrize("resolver", [real_window_resolver, real_grid_resolver], ids=lambda f: f.__name__)
def test_the_real_resolvers_route_every_gaze_trial_to_the_pane_it_asked_for(seed, resolver):
    task = generate_task(GAZE_TASK, seed)
    records = run_gaze(task, resolver(task))
    assert check_records(task, records) == []
    metrics = tally(task, records)
    assert metrics["correct_target"] == task["scored_trials"], metrics
    assert metrics["wrong_target"] == 0 and metrics["fallback_no_route"] == 0
    assert completeness_verdict(task, records) == "PASS"


@pytest.mark.parametrize("seed", SEEDS, ids=_seed_id)
@pytest.mark.parametrize("name", sorted(GAZE_MUTANTS))
def test_each_wrong_gaze_resolver_is_caught_with_the_count_the_task_implies(seed, name):
    """The expected number of wrong trials comes from the sequence, not from the run."""
    task = generate_task(GAZE_TASK, seed)
    mutant = GAZE_MUTANTS[name](task)
    centres = {p["target_id"]: (p["center_x"], p["center_y"]) for p in task["targets"]}
    # What the mutant does to each pane, read off the geometry rather than assumed.
    answer_for = {pane: mutant(*centre) for pane, centre in centres.items()}
    asked = [t["intended_target_id"] for b in scored_blocks(task) for t in b["trials"]]
    expected_wrong = sum(1 for pane in asked if answer_for[pane] != pane)
    assert expected_wrong > 0, f"mutant {name!r} agrees with the task on every pane: fixture is blind to it"

    metrics = tally(task, run_gaze(task, mutant))
    assert metrics["wrong_target"] + metrics["fallback_no_route"] == expected_wrong
    assert metrics["correct_target"] == len(asked) - expected_wrong
    assert metrics["correct_target"] < task["scored_trials"]


def test_a_gaze_point_between_or_outside_the_panes_has_no_route():
    """The gap and the margin are part of the geometry, and a real resolver returns None there."""
    task = generate_task(GAZE_TASK)
    resolve = real_window_resolver(task)
    by_id = {p["target_id"]: p for p in task["targets"]}
    left, right = by_id[1], by_id[2]
    gap_x = (left["center_x"] + left["width"] // 2 + right["center_x"] - right["width"] // 2) // 2
    assert resolve(gap_x, left["center_y"]) is None, "inside the gap between panes 1 and 2"
    assert resolve(left["center_x"] - left["width"] // 2 - 1, left["center_y"]) is None, "in the margin"
    # The pane edge: the low edge belongs to the pane, the high edge to the neighbour/None.
    assert resolve(left["center_x"] - left["width"] // 2, left["center_y"]) == 1
    assert resolve(left["center_x"] + left["width"] // 2, left["center_y"]) is None


def test_a_resolver_that_never_routes_is_counted_as_fallback_not_as_correct():
    task = generate_task(GAZE_TASK)
    metrics = tally(task, run_gaze(task, lambda _x, _y: None))
    assert metrics["fallback_no_route"] == task["scored_trials"]
    assert metrics["correct_target"] == 0 and metrics["wrong_target"] == 0


# =========================================================================================
# head pointer: a closed-loop simulated head, steered by the real mapping and dwell
# =========================================================================================

FRAME_S = 1.0 / 30.0
MAX_TRIAL_S = 20.0
#: How hard the simulated head turns per pixel of remaining distance (1/s). A property of
#: the simulation, not of any person: it only has to be a plausible steering law whose
#: stopping point is knowable.
STEER_PER_S = 3.0


def inside(target: dict[str, Any], x: float, y: float) -> bool:
    """Whether a point is inside a target's rectangle: the task's own geometry, per-mille."""
    return (
        abs(x - target["center_x"]) * 2 <= target["width"]
        and abs(y - target["center_y"]) * 2 <= target["height"]
    )


PoseFn = Callable[..., "tuple[float, float]"]
ClickerFactory = Callable[[], DwellClicker]


def _real_pose(yaw: float, pitch: float, calib: PointerCalib = PointerCalib()) -> tuple[float, float]:
    return pose_to_cursor(yaw, pitch, calib)


def _y_inverted(yaw: float, pitch: float, calib: PointerCalib = PointerCalib()) -> tuple[float, float]:
    vx, vy = pose_to_cursor(yaw, pitch, calib)
    return (vx, -vy)


def fly(
    block: dict[str, Any],
    trial: dict[str, Any],
    *,
    pose: PoseFn = _real_pose,
    clicker: ClickerFactory = DwellClicker,
) -> dict[str, Any]:
    """One trial: steer from `(start_x, start_y)` to the target and let the dwell click.

    One per-mille is one pixel on a 1000 x 1000 display, so the real pixel-denominated
    constants (dwell radius, speed caps) act on the task's geometry directly.
    """
    calib = PointerCalib()
    target = next(t for t in block["targets"] if t["target_id"] == trial["target_id"])
    x, y = float(trial["start_x"]), float(trial["start_y"])
    dwell = clicker()
    previous = 0.0
    first_move_ms: int | None = None
    last_move_ms: int | None = None
    steps = int(MAX_TRIAL_S / FRAME_S)
    for step in range(1, steps + 1):
        now = step * FRAME_S
        want_vx = STEER_PER_S * (target["center_x"] - x)
        want_vy = STEER_PER_S * (target["center_y"] - y)
        vx, vy = pose(want_vx / calib.x_gain, want_vy / calib.y_gain, calib)
        vx, vy = limit_velocity(vx, vy, calib)
        dt = elapsed_s(previous, now)
        x, y = x + vx * dt, y + vy * dt
        previous = now
        if vx or vy:
            first_move_ms = int(now * 1000) if first_move_ms is None else first_move_ms
            last_move_ms = int(now * 1000)
        if dwell.update(x, y, now):
            return {
                "trial_index": trial["trial_index"],
                "target_id": trial["target_id"],
                "outcome": "hit" if inside(target, x, y) else "miss",
                "movement_start_ms": first_move_ms if first_move_ms is not None else int(now * 1000),
                "movement_end_ms": last_move_ms if last_move_ms is not None else int(now * 1000),
                "click_ms": int(now * 1000),
                "hold_s": dwell.hold_s,
            }
    return {
        "trial_index": trial["trial_index"],
        "target_id": trial["target_id"],
        "outcome": "abandoned",
    }


def run_pointer(task: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    return [fly(block, trial, **kwargs) for block in scored_blocks(task) for trial in block["trials"]]


def _public(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The fields a run may record (`hold_s` is the simulation's own bookkeeping)."""
    return [{k: v for k, v in r.items() if k != "hold_s"} for r in records]


POINTER_MUTANTS: dict[str, dict[str, Any]] = {
    # The vertical axis points the wrong way: the geometry bug a mapping change would cause.
    "y_axis_inverted": {"pose": _y_inverted},
    # A dwell radius so large that "still" means "anywhere": the click fires mid-flight.
    "dwell_radius_unbounded": {"clicker": lambda: DwellClicker(radius=5000.0)},
    # No dwell at all: the click fires on the next sample, wherever the pointer is.
    "dwell_hold_zero": {"clicker": lambda: DwellClicker(hold_s=0.0)},
}


@pytest.mark.parametrize("seed", SEEDS, ids=_seed_id)
def test_the_real_pointer_code_hits_every_target_the_task_asks_for(seed):
    task = generate_task(HEAD_POINTER_TASK, seed)
    records = run_pointer(task)
    outcomes = [r["outcome"] for r in records]
    assert outcomes == ["hit"] * task["scored_trials"], outcomes
    assert check_records(task, _public(records)) == []
    metrics = tally(task, _public(records))
    assert metrics["hit"] == task["scored_trials"]
    assert metrics["completion_rate"] == 1.0
    assert completeness_verdict(task, _public(records)) == "PASS"


def test_a_click_never_lands_before_the_dwell_has_elapsed():
    """Movement and click are separate records for a reason: the dwell lies between them."""
    task = generate_task(HEAD_POINTER_TASK)
    for record in run_pointer(task):
        hold_ms = record["hold_s"] * 1000
        assert record["click_ms"] - record["movement_start_ms"] >= hold_ms - 1, record
        assert record["movement_end_ms"] <= record["click_ms"]


def test_the_timed_records_reach_the_tally_as_a_movement_time():
    task = generate_task(HEAD_POINTER_TASK)
    records = _public(run_pointer(task))
    durations = sorted(r["movement_end_ms"] - r["movement_start_ms"] for r in records)
    middle = len(durations) // 2
    expected = (durations[middle - 1] + durations[middle]) / 2 if len(durations) % 2 == 0 else durations[middle]
    got = tally(task, records)["movement_time_ms_p50"]
    assert math.isclose(got, expected, abs_tol=0.06), (got, expected)


@pytest.mark.parametrize("name", sorted(POINTER_MUTANTS))
def test_each_wrong_pointer_implementation_is_caught(name):
    task = generate_task(HEAD_POINTER_TASK)
    records = run_pointer(task, **POINTER_MUTANTS[name])
    hits = sum(1 for r in records if r["outcome"] == "hit")
    assert hits < task["scored_trials"], f"mutant {name!r} hit every target: fixture is blind to it"
    metrics = tally(task, _public(records))
    assert metrics["completion_rate"] < 1.0
    assert metrics["hit"] == hits


def test_a_target_the_pointer_stops_short_of_is_a_miss_not_a_hit():
    """`inside` is the oracle for every pointer verdict above, so it gets its own edge cases."""
    task = generate_task(HEAD_POINTER_TASK)
    target = scored_blocks(task)[0]["targets"][0]
    half = target["width"] // 2
    cx, cy = target["center_x"], target["center_y"]
    assert inside(target, cx, cy)
    assert inside(target, cx + half, cy + half), "the boundary is inside"
    assert not inside(target, cx + half + 0.5, cy)
    assert not inside(target, cx, cy - half - 0.5)


# =========================================================================================
# face switch: a numeric trace laid out from the task, replayed through the real switch
# =========================================================================================

RATE_HZ = 100
#: How long the simulated gesture is held, and the score it holds at. Inventions chosen to
#: sit clearly above the shipped hold threshold and well inside the gap between cues.
GESTURE_SAMPLES = RATE_HZ  # one second
GESTURE_SCORE = 0.9
REST_SCORE = 0.05
#: A jaw movement while talking: brief, and as strong as the deliberate gesture.
SPEECH_BLIP_SAMPLES = 5
SPEECH_BLIP_OFFSET_S = 5
#: A shorter twitch later in the same prompt, below the shipped debounce: not an activation.
SPEECH_TWITCH_SAMPLES = 2
SPEECH_TWITCH_OFFSET_S = 25
GESTURE = "jaw_open"


def cue_sample(cue_ms: int) -> int:
    return cue_ms * RATE_HZ // 1000


def switch_trace_for(task: dict[str, Any], block: dict[str, Any]) -> dict[str, Any]:
    """The numeric trace for one block of the face-switch task.

    neutral   -> rest throughout; the right answer is zero activations.
    deliberate-> a held gesture starting exactly at each cue; the right answer is one
                 detection per cue and nothing else.
    speaking  -> speech throughout; each prompt's share of the block has one brief jaw
                 movement (long enough to activate) and one shorter twitch (not long enough);
                 the right answer is one phantom per prompt, in 'speech'.
    """
    total = block["duration_s"] * RATE_HZ
    scores = [REST_SCORE] * total
    segments: list[dict[str, Any]] = []
    if block["block_type"] == "deliberate":
        cursor = 0
        for cue_ms in block["cue_times_ms"]:
            start = cue_sample(cue_ms)
            segments.append({"context": "rest", "samples": start - cursor})
            segments.append({"context": "deliberate", "samples": GESTURE_SAMPLES})
            scores[start : start + GESTURE_SAMPLES] = [GESTURE_SCORE] * GESTURE_SAMPLES
            cursor = start + GESTURE_SAMPLES
        segments.append({"context": "rest", "samples": total - cursor})
    elif block["block_type"] == "speaking":
        share = total // len(block["prompts"])
        for index in range(len(block["prompts"])):
            start = index * share + SPEECH_BLIP_OFFSET_S * RATE_HZ
            scores[start : start + SPEECH_BLIP_SAMPLES] = [GESTURE_SCORE] * SPEECH_BLIP_SAMPLES
            twitch = index * share + SPEECH_TWITCH_OFFSET_S * RATE_HZ
            scores[twitch : twitch + SPEECH_TWITCH_SAMPLES] = [GESTURE_SCORE] * SPEECH_TWITCH_SAMPLES
        segments.append({"context": "speech", "samples": total})
    else:
        segments.append({"context": "rest", "samples": total})
    return {
        "schema_version": "1.0",
        "trace_id": f"task-{task['seed']}-{block['block_id']}",
        "study_mode": "synthetic",
        "gesture": GESTURE,
        "sample_rate_hz": RATE_HZ,
        "description": "Invented trace laid out from a task fixture; not a measurement.",
        "segments": segments,
        "scores": scores,
    }


def switch_violations(task: dict[str, Any], config: SwitchConfig) -> list[str]:
    """Every way a switch configuration disagrees with the answer the task implies."""
    out: list[str] = []
    for block in task["blocks"]:
        trace = check_trace(json.loads(json.dumps(switch_trace_for(task, block))))
        result = replay_trace(trace, config)
        kind, name = block["block_type"], block["block_id"]
        if kind == "deliberate":
            cues = block["cue_times_ms"]
            if len(result.intervals) != len(cues):
                out.append(f"{name}: {len(result.intervals)} intervals for {len(cues)} cues")
                continue
            for index, (interval, cue_ms) in enumerate(zip(result.intervals, cues, strict=True)):
                if interval.start != cue_sample(cue_ms):
                    out.append(f"{name}.{index}: interval starts at {interval.start}, cue at {cue_sample(cue_ms)}")
                if len(interval.starts) != 1:
                    out.append(f"{name}.{index}: {len(interval.starts)} activations for one cue")
            if result.phantom_samples:
                out.append(f"{name}: {len(result.phantom_samples)} activations away from every cue")
        elif kind == "speaking":
            if len(result.phantom_samples) != len(block["prompts"]):
                out.append(
                    f"{name}: {len(result.phantom_samples)} phantoms for {len(block['prompts'])} prompts"
                )
            if set(result.phantom_contexts) - {"speech"}:
                out.append(f"{name}: phantom attributed to {set(result.phantom_contexts)}")
        elif result.phantom_samples:
            out.append(f"{name}: {len(result.phantom_samples)} activations at rest")
    return out


@pytest.mark.parametrize("seed", SEEDS, ids=_seed_id)
def test_the_real_switch_answers_every_cue_and_nothing_else(seed):
    task = generate_task(FACE_SWITCH_TASK, seed)
    assert switch_violations(task, SwitchConfig()) == []


def test_the_traces_are_laid_out_from_the_task_not_from_numbers_in_this_file():
    task = generate_task(FACE_SWITCH_TASK)
    deliberate = next(b for b in task["blocks"] if b["block_type"] == "deliberate")
    trace = check_trace(json.loads(json.dumps(switch_trace_for(task, deliberate))))
    labelled = [s for s in trace.segments if s.context == "deliberate"]
    assert len(labelled) == len(deliberate["cue_times_ms"]) == task["scored_trials"]
    assert trace.samples == deliberate["duration_s"] * RATE_HZ
    speaking = next(b for b in task["blocks"] if b["block_type"] == "speaking")
    assert len(speaking["prompts"]) == len(SPEAKING_PROMPTS)


SWITCH_MUTANTS = {
    # Never fires on a clearly deliberate gesture: recall collapses.
    "threshold_above_the_gesture": SwitchConfig(hold_threshold=0.95),
    # Fires on rest: a hair trigger below the resting level.
    "hair_trigger_below_rest": SwitchConfig(hold_threshold=0.04, release_threshold=0.02),
    # Needs the gesture held for longer than the task's cue ever holds it.
    "debounce_longer_than_the_gesture": SwitchConfig(min_hold_frames=GESTURE_SAMPLES * 2),
    # Accepts a single stray frame, so the twitch while speaking activates as well.
    "no_debounce": SwitchConfig(min_hold_frames=1),
}


@pytest.mark.parametrize("name", sorted(SWITCH_MUTANTS))
def test_each_wrong_switch_configuration_is_caught(name):
    task = generate_task(FACE_SWITCH_TASK)
    violations = switch_violations(task, SWITCH_MUTANTS[name])
    assert violations, f"mutant {name!r} satisfied the task: fixture is blind to it"


def test_the_blip_and_the_twitch_straddle_the_shipped_debounce():
    """The speaking block has a boundary: one movement above the debounce, one below it."""
    shipped = SwitchConfig()
    assert SPEECH_TWITCH_SAMPLES < shipped.min_hold_frames < SPEECH_BLIP_SAMPLES
    longer_debounce = SwitchConfig(min_hold_frames=SPEECH_BLIP_SAMPLES + 1)
    task = generate_task(FACE_SWITCH_TASK)
    assert any("phantoms" in v for v in switch_violations(task, longer_debounce))


def test_every_gesture_the_trace_uses_is_one_the_switch_knows():
    assert GESTURE in GESTURES


# =========================================================================================
# the fixtures carry nothing but the task
# =========================================================================================


def _string_leaves(node: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(node, str):
        return [(path, node)]
    if isinstance(node, dict):
        return [leaf for k, v in node.items() for leaf in _string_leaves(v, f"{path}{k}.")]
    if isinstance(node, list):
        return [leaf for i, v in enumerate(node) for leaf in _string_leaves(v, f"{path}{i}.")]
    return []


#: Free text that is allowed to be a sentence: the human description, the stated
#: limitations, and the public pangrams. Everything else must be an identifier-shaped token.
PROSE_KEYS = ("description", "limitations", "prompts")


@pytest.mark.parametrize("task_id", TASK_IDS)
@pytest.mark.parametrize("seed", SEEDS, ids=_seed_id)
def test_a_fixture_holds_identifiers_and_public_prose_and_nothing_else(task_id, seed):
    """No real participant data and no raw frames can hide in a generated fixture.

    A frame, a window title or a transcript would have to be a long or free-form string, or
    a long list of numbers. Every string outside the prose keys is therefore required to be
    a short identifier, and the whole document is size-bounded.
    """
    doc = generate_task(task_id, seed)
    assert validate_task(doc) == []
    for path, text in _string_leaves(doc):
        if any(f".{key}." in f".{path}" or path.startswith(f"{key}") for key in PROSE_KEYS):
            continue
        assert len(text) <= 40 and all(c.isalnum() or c in "_.:/-+ " for c in text), (path, text)
    assert len(dump_task(doc)) < 20_000, "a task is a schedule, not a recording"


def test_the_prompts_are_exactly_the_public_sentences():
    doc = generate_task(FACE_SWITCH_TASK)
    spoken = [p for b in doc["blocks"] for p in b["prompts"]]
    assert spoken == list(SPEAKING_PROMPTS)


def test_every_task_has_a_checked_in_fixture_and_a_seed():
    assert set(DEFAULT_SEEDS) == set(TASK_IDS) == set(FIXTURE_FILENAMES)
