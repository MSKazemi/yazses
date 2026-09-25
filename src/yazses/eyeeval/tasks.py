"""Deterministic eye/camera evaluation *tasks* -- the inputs a run replays.

`yazses.eyeeval.schema` describes the envelope a finished result arrives in. This module
describes the other half: the task a tester actually performs, frozen hard enough that two
people on two machines did the same thing. Without that, "35 of 40 correct" on one laptop
and "35 of 40" on another are two numbers about two different experiments, and comparing
them is arithmetic rather than measurement.

Three tasks, one per modality, named exactly as the result envelope's `protocol.task`
already spells them (see the shipped result fixtures under `tests/fixtures/eye_eval/`):

* `gaze_routing_4_pane` -- four large numbered panes, a balanced 40-trial sequence;
* `head_pointer_generated_targets` -- a ring of large generated targets, ISO-style
  alternating order, three width/amplitude conditions;
* `face_switch_blocks` -- a cued deliberate block, a neutral block and a normal-speaking
  block, so a false activation is attributable to the state the person was in.

## What makes these replayable rather than merely written down

**Generated content only.** Every target is a rectangle this module computes. Nothing reads
the desktop, so no screenshot, window title, document text or private content can enter a
task -- which is what `design/eye-control/EVALUATION.md` means by "use large generated
targets so the task does not depend on private desktop content".

**Integer per-mille geometry.** Positions and sizes are integers in thousandths of the
logical display, never pixels and never floats. Pixels would bind a task to one screen;
floats would bind its checked-in form to one platform's formatting and, worse, invite
`cos`/`sqrt` into the generator, whose last bit is not guaranteed identical across C
libraries. The diagonal of the pointer ring is therefore the exact integer ratio 707/1000,
not `1/sqrt(2)`. A fixture that regenerates byte-for-byte on Windows, macOS and Linux is
the whole point, and integers are how it is bought.

**A pseudo-random generator written out in full.** Sequence order is shuffled from a
recorded seed by the SplitMix64 mixing function below, not by `secrets` or by the standard
library's Mersenne Twister. The standard library's shuffle is an implementation detail of
an interpreter version; a fixture generated under one Python and replayed under another has
to produce the same order, so the algorithm is spelled out here and owned here.

**Two version numbers, because two different things change.** `fixture_schema_version` is
the envelope -- the field names and shapes below. `task_version` is the protocol content:
how many trials, how large the targets are, how long a block runs. A reader that ignores
the second can silently compare a 40-trial run against a 60-trial one, so `validate_task`
refuses a fixture whose `task_version` is not the one this module implements. Changing what
a number means requires bumping that version and therefore shows up in a diff.

## What these fixtures are not

They fix *what was asked*, never *what happened*, and they contain no measurement at all.
Nothing here may be read as a threshold, a target value or a recommended default: a
generated task can tell you a tester was asked to hit a 120-per-mille target, and nothing
whatever about how wide a target YazSes should ship. Defaults need real cross-person data
(`design/eye-control/EVALUATION.md` promotion gates, ADR-v2-150), and synthetic inputs
cannot supply it.

Pure stdlib, no camera, no clock, no network, no file I/O. Nothing in the daemon imports
it; it exists for the local runner (#423) and the non-hardware CI matrix (#424).

## How a runner loads one

    from yazses.eyeeval import TASK_IDS, check_task, generate_task

    doc = generate_task("gaze_routing_4_pane")   # same bytes on every machine
    check_task(doc)                              # raises with every problem at once

The checked-in copies under `tests/fixtures/eye_eval_tasks/<task_id>.json` are the frozen
expected output of exactly that call, in the canonical form `dump_task` writes. They are a
regression anchor for CI and a human-readable artifact to publish beside a result; a runner
on a user's machine should call the generator, which needs no data files installed.
"""

from __future__ import annotations

import json
from typing import Any, TypeGuard

from yazses.eyeeval.schema import FEATURES, forbidden_field_problems

#: The task-fixture *envelope* version. Add a field, bump the minor; change or remove one,
#: bump the major. Same rule, and the same reason, as the result schema.
FIXTURE_SCHEMA_VERSION = "1.0"
SUPPORTED_FIXTURE_MAJOR = 1

#: Geometry is integer thousandths of the logical display, so a task means the same thing
#: on a 1366x768 laptop and a 4K panel at 200% scale. The canvas is 1000 x 1000 by
#: definition; a runner multiplies by the real display rectangle.
GEOMETRY_UNITS = "permille"
CANVAS_PERMILLE = 1000

GAZE_TASK = "gaze_routing_4_pane"
HEAD_POINTER_TASK = "head_pointer_generated_targets"
FACE_SWITCH_TASK = "face_switch_blocks"

#: The task identifiers, spelled as the result envelope's `protocol.task` already spells
#: them. A closed set: a typo is a failure, not a new silently-unaggregated task.
TASK_IDS = (GAZE_TASK, HEAD_POINTER_TASK, FACE_SWITCH_TASK)

#: The protocol content version each task is at. Bumping one is how a change to trial
#: count, target size or block duration becomes visible instead of quietly changing what a
#: published number means.
TASK_VERSIONS: dict[str, str] = {
    GAZE_TASK: "1.0",
    HEAD_POINTER_TASK: "1.0",
    FACE_SWITCH_TASK: "1.0",
}

#: Which metric family in `design/eye-control/METRICS.md` a task feeds. Values are members
#: of `schema.FEATURES`, checked by the tests rather than assumed.
TASK_FEATURES: dict[str, str] = {
    GAZE_TASK: "gaze",
    HEAD_POINTER_TASK: "head_pointer",
    FACE_SWITCH_TASK: "face_switch",
}

#: One fixed seed per task, recorded in the fixture. A tester may pass another to get a
#: different counterbalanced order; the shipped fixtures use these.
DEFAULT_SEEDS: dict[str, int] = {
    GAZE_TASK: 2026092501,
    HEAD_POINTER_TASK: 2026092502,
    FACE_SWITCH_TASK: 2026092503,
}

#: The frozen artifact for each task, under `tests/fixtures/eye_eval_tasks/`.
FIXTURE_FILENAMES: dict[str, str] = {task_id: f"{task_id}.json" for task_id in TASK_IDS}

#: A block is either practice (excluded from every count) or scored.
BLOCK_KINDS = ("practice", "scored")

#: The per-trial outcome vocabulary each task records. Closed, and deliberately keeping
#: "wrong target" apart from "declined to act": `METRICS.md` is explicit that collapsing
#: them into one "error" hides the safer of the two behaviours.
TASK_OUTCOMES: dict[str, tuple[str, ...]] = {
    GAZE_TASK: ("correct", "wrong_target", "fallback_no_route", "invalid_tracking"),
    HEAD_POINTER_TASK: ("hit", "miss", "abandoned", "tracking_lost"),
    FACE_SWITCH_TASK: ("detected", "missed", "false_activation"),
}

#: The fields a runner may record per trial. Derived numbers, indices and enum members
#: only -- there is no field here that could hold desktop text, a frame, or who the tester
#: is, which is the same structural argument the result schema makes.
TASK_RECORDS: dict[str, tuple[str, ...]] = {
    GAZE_TASK: (
        "trial_index",
        "intended_target_id",
        "outcome",
        "confidence_bucket",
        "calibration_age_s",
        "trial_time_ms",
    ),
    HEAD_POINTER_TASK: (
        "trial_index",
        "target_id",
        "outcome",
        "movement_start_ms",
        "movement_end_ms",
        # Distinct from `movement_end_ms` on purpose: a dwell click fires after the pointer
        # has already settled, so collapsing the two would hide the dwell interval.
        "click_ms",
        "miss_count",
        "recenter_count",
        "tracking_loss_ms",
        "accidental_click_count",
    ),
    FACE_SWITCH_TASK: (
        "block_id",
        "block_type",
        "cue_index",
        "outcome",
        "activation_latency_ms",
        "detection_count",
        "miss_count",
        "false_activation_count",
    ),
}

#: The tasks that draw something on screen, and therefore declare a coordinate space. The
#: face-switch task has no on-screen target at all, so it declares no geometry rather than
#: carrying a canvas nothing is measured against.
GEOMETRY_TASKS = (GAZE_TASK, HEAD_POINTER_TASK)

#: A task fixture describes generated content and nothing else. The literal is the only
#: accepted value, so a fixture cannot quietly start describing a capture of a real screen.
CONTENT_SOURCES = ("generated",)

REQUIRED_TASK_FIELDS = (
    "fixture_schema_version",
    "task_id",
    "task_version",
    "feature",
    "description",
    "generator",
    "seed",
    "records",
    "outcomes",
    "blocks",
    "scored_trials",
    "privacy",
)
#: Required on top of `REQUIRED_TASK_FIELDS`, for a task with on-screen geometry.
REQUIRED_GEOMETRY_FIELDS = ("geometry_units", "canvas_permille")
REQUIRED_PRIVACY_FIELDS = (
    "content_source",
    "raw_media_retained",
    "contains_personal_identifiers",
)

# --- gaze task parameters -----------------------------------------------------------

GAZE_TARGET_COUNT = 4
GAZE_MARGIN_PERMILLE = 20
GAZE_GAP_PERMILLE = 20
#: Ten balanced rounds of all four panes: 40 scored trials, 10 per pane, which is the QA
#: block size `design/eye-control/EVALUATION.md` recommends.
GAZE_SCORED_ROUNDS = 10

#: A gaze pane has to be far larger than a plausible calibration error, or the task
#: measures calibration precision instead of routing. This floor is a property of the
#: *task design*; it is emphatically not a claim about how large a real UI target must be.
MIN_GAZE_PANE_PERMILLE = 300

# --- head-pointer task parameters ---------------------------------------------------

POINTER_RING_POSITIONS = 8
#: ISO 9241-9 style alternation: every movement crosses the centre, so no trial is a short
#: hop to a neighbour and the amplitude of each trial is known in advance.
POINTER_ISO_ORDER = (0, 4, 1, 5, 2, 6, 3, 7)
#: (ring radius, target edge), both per-mille. Two edges at one radius and one shorter
#: radius: enough to tell "slower because further" from "slower because smaller" without
#: turning a QA block into a study.
POINTER_CONDITIONS = ((350, 120), (350, 80), (250, 120))
POINTER_PRACTICE_CONDITION = (350, 120)
POINTER_PRACTICE_TRIALS = 4
#: 1/sqrt(2) as an exact integer ratio. Written this way on purpose: no transcendental
#: function runs in this module, so the fixture's bytes cannot depend on a C library.
DIAGONAL_RATIO_PER_MILLE = 707
#: Large enough that the task is not a precision test. Again: a task-design floor, not a
#: recommended minimum control size for the product.
MIN_POINTER_TARGET_PERMILLE = 60

# --- face-switch task parameters ----------------------------------------------------

SWITCH_BLOCK_DURATION_S = 300
SWITCH_CUE_COUNT = 30
SWITCH_FIRST_CUE_MS = 5_000
SWITCH_CUE_INTERVAL_MS = 10_000
#: Cues sit on a 10 s grid jittered by up to +/-2 s. A metronome would let a tester
#: anticipate, and anticipation is not the thing being measured; the jitter is bounded so
#: the minimum gap between cues stays far above any plausible refractory interval.
SWITCH_CUE_JITTER_MS = 2_000

#: The three blocks, in the order they are run. `design/eye-control/EVALUATION.md` requires
#: all three and requires the neutral and speaking blocks to stay separately identifiable:
#: a switch that fires while someone talks is a different defect from one that fires at
#: rest. Neutral runs first so a baseline exists before any deliberate activation.
SWITCH_BLOCK_TYPES = ("neutral", "deliberate", "speaking")

#: Sentences for the speaking block. Well-known pangrams: fixed, public, meaningless, and
#: heavy on jaw and lip movement, which is the point -- a mouth gesture has to survive
#: ordinary speech. A tester reads these aloud instead of saying something of their own,
#: so nothing private is spoken and nothing at all is recorded (`DATA_SHARING.md`).
SPEAKING_PROMPTS = (
    "The quick brown fox jumps over the lazy dog.",
    "Sphinx of black quartz, judge my vow.",
    "How vexingly quick daft zebras jump.",
    "The five boxing wizards jump quickly.",
    "Jackdaws love my big sphinx of quartz.",
    "Bright vixens jump; dozy fowl quack.",
)

GENERATOR = f"yazses.eyeeval.tasks/{FIXTURE_SCHEMA_VERSION}"

_MASK64 = (1 << 64) - 1
_GOLDEN_GAMMA = 0x9E3779B97F4A7C15
_MIX_A = 0xBF58476D1CE4E5B9
_MIX_B = 0x94D049BB133111EB


class EyeEvalTaskError(ValueError):
    """One or more task-fixture violations, listed one per line."""


class _SplitMix64:
    """SplitMix64, written out so a fixture's order is owned by this file.

    `random.shuffle` would be shorter and is a worse choice here: it is an interpreter
    implementation detail, and a task fixture generated under one Python and regenerated
    under another has to produce identical bytes or the byte-stability check becomes a
    false red. The algorithm below is fully specified in integer arithmetic and cannot
    drift.
    """

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = seed & _MASK64

    def next_u64(self) -> int:
        self._state = (self._state + _GOLDEN_GAMMA) & _MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * _MIX_A) & _MASK64
        z = ((z ^ (z >> 27)) * _MIX_B) & _MASK64
        return z ^ (z >> 31)

    def below(self, bound: int) -> int:
        """A uniform integer in [0, bound), by rejection -- modulo alone would bias it."""
        if bound <= 0:
            raise ValueError("bound must be positive")
        limit = (1 << 64) - ((1 << 64) % bound)
        while True:
            draw = self.next_u64()
            if draw < limit:
                return draw % bound

    def shuffled(self, items: tuple[Any, ...]) -> list[Any]:
        """Fisher-Yates, descending, so one draw is consumed per position."""
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self.below(i + 1)
            out[i], out[j] = out[j], out[i]
        return out


def _square(center_x: int, center_y: int, edge: int) -> dict[str, int]:
    return {"center_x": center_x, "center_y": center_y, "width": edge, "height": edge}


def _privacy() -> dict[str, Any]:
    return {
        "content_source": "generated",
        "raw_media_retained": False,
        "contains_personal_identifiers": False,
    }


def _envelope(task_id: str, seed: int, description: str) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
        "task_id": task_id,
        "task_version": TASK_VERSIONS[task_id],
        "feature": TASK_FEATURES[task_id],
        "description": description,
        "generator": GENERATOR,
        "seed": seed,
    }
    if task_id in GEOMETRY_TASKS:
        doc["geometry_units"] = GEOMETRY_UNITS
        doc["canvas_permille"] = {"width": CANVAS_PERMILLE, "height": CANVAS_PERMILLE}
    doc["records"] = list(TASK_RECORDS[task_id])
    doc["outcomes"] = list(TASK_OUTCOMES[task_id])
    return doc


# --- gaze ---------------------------------------------------------------------------


def gaze_panes() -> list[dict[str, Any]]:
    """Four equal panes in a 2x2 grid, numbered left-to-right then top-to-bottom.

    The prompt says "look at target 3", so the label is the number and nothing else: there
    is no pane title, no icon and no desktop content to read.
    """
    edge = (CANVAS_PERMILLE - 2 * GAZE_MARGIN_PERMILLE - GAZE_GAP_PERMILLE) // 2
    half = edge // 2
    low = GAZE_MARGIN_PERMILLE + half
    high = CANVAS_PERMILLE - GAZE_MARGIN_PERMILLE - half
    panes = []
    for index, (cx, cy) in enumerate(((low, low), (high, low), (low, high), (high, high))):
        target_id = index + 1
        panes.append({"target_id": target_id, "label": str(target_id), **_square(cx, cy, edge)})
    return panes


def gaze_sequence(seed: int) -> list[int]:
    """`GAZE_SCORED_ROUNDS` balanced rounds, with no pane asked for twice in a row.

    Balance is structural: each round is a permutation of all four panes, so the totals are
    equal by construction rather than by luck with a seed. The only repair needed is at a
    round boundary, where the previous round's last pane may equal this round's first --
    swapping the first two entries of the new round fixes it and cannot fail, because the
    four entries of a round are distinct.
    """
    rng = _SplitMix64(seed)
    ids = tuple(range(1, GAZE_TARGET_COUNT + 1))
    out: list[int] = []
    for _ in range(GAZE_SCORED_ROUNDS):
        block = rng.shuffled(ids)
        if out and block[0] == out[-1]:
            block[0], block[1] = block[1], block[0]
        out += block
    return out


def generate_gaze_task(seed: int | None = None) -> dict[str, Any]:
    seed = DEFAULT_SEEDS[GAZE_TASK] if seed is None else seed
    panes = gaze_panes()
    practice = [
        {"trial_index": i, "intended_target_id": pane["target_id"]}
        for i, pane in enumerate(panes)
    ]
    scored = [
        {"trial_index": i, "intended_target_id": target_id}
        for i, target_id in enumerate(gaze_sequence(seed))
    ]
    doc = _envelope(
        GAZE_TASK,
        seed,
        "Four large numbered panes. Each trial prompts one pane by its number, the tester "
        "triggers the ordinary gaze-routing moment, and the run records the intended pane "
        "and the resolved outcome -- nothing about what the panes contain, because they "
        "contain only a number.",
    )
    doc["targets"] = panes
    doc["blocks"] = [
        {"block_id": "practice", "kind": "practice", "trials": practice},
        {"block_id": "scored", "kind": "scored", "trials": scored},
    ]
    doc["scored_trials"] = len(scored)
    doc["privacy"] = _privacy()
    return doc


# --- head pointer -------------------------------------------------------------------


def pointer_ring(radius: int, edge: int) -> list[dict[str, Any]]:
    """Eight targets on a ring of `radius`, index 0 at the right, going clockwise.

    Clockwise in screen coordinates, where y increases downward: 0 right, 2 down, 4 left,
    6 up. The diagonal offset is `radius * 707 // 1000` rounded to the nearest integer, so
    every coordinate is exact and the four diagonal amplitudes are honestly a shade under
    the four axis ones.
    """
    diagonal = (radius * DIAGONAL_RATIO_PER_MILLE + 500) // 1000
    centre = CANVAS_PERMILLE // 2
    offsets = (
        (radius, 0),
        (diagonal, diagonal),
        (0, radius),
        (-diagonal, diagonal),
        (-radius, 0),
        (-diagonal, -diagonal),
        (0, -radius),
        (diagonal, -diagonal),
    )
    return [
        {"target_id": index, **_square(centre + dx, centre + dy, edge)}
        for index, (dx, dy) in enumerate(offsets)
    ]


def _pointer_block(block_id: str, kind: str, radius: int, edge: int, count: int) -> dict[str, Any]:
    targets = pointer_ring(radius, edge)
    centre = CANVAS_PERMILLE // 2
    start_x, start_y = centre, centre
    trials = []
    for trial_index, ring_index in enumerate(POINTER_ISO_ORDER[:count]):
        target = targets[ring_index]
        trials.append(
            {
                "trial_index": trial_index,
                "target_id": ring_index,
                "start_x": start_x,
                "start_y": start_y,
                "dx": target["center_x"] - start_x,
                "dy": target["center_y"] - start_y,
            }
        )
        start_x, start_y = target["center_x"], target["center_y"]
    return {
        "block_id": block_id,
        "kind": kind,
        "radius_permille": radius,
        "target_width_permille": edge,
        "targets": targets,
        "trials": trials,
    }


def generate_head_pointer_task(seed: int | None = None) -> dict[str, Any]:
    seed = DEFAULT_SEEDS[HEAD_POINTER_TASK] if seed is None else seed
    rng = _SplitMix64(seed)
    order = rng.shuffled(POINTER_CONDITIONS)
    practice_radius, practice_edge = POINTER_PRACTICE_CONDITION
    blocks: list[dict[str, Any]] = [
        _pointer_block("practice", "practice", practice_radius, practice_edge,
                       POINTER_PRACTICE_TRIALS)
    ]
    for index, (radius, edge) in enumerate(order):
        blocks.append(
            _pointer_block(f"scored_{index + 1}", "scored", radius, edge, POINTER_RING_POSITIONS)
        )
    doc = _envelope(
        HEAD_POINTER_TASK,
        seed,
        "A ring of eight large generated targets, visited in an alternating order so every "
        "movement crosses the centre and its amplitude is known before the trial starts. "
        "Three width/radius conditions run in a seeded order; the geometry is generated, so "
        "the task never depends on what is on the tester's desktop.",
    )
    doc["condition_order"] = [
        {"radius_permille": radius, "target_width_permille": edge} for radius, edge in order
    ]
    doc["blocks"] = blocks
    doc["scored_trials"] = sum(len(b["trials"]) for b in blocks if b["kind"] == "scored")
    doc["privacy"] = _privacy()
    return doc


# --- face switch --------------------------------------------------------------------


def switch_cue_times_ms(seed: int) -> list[int]:
    """`SWITCH_CUE_COUNT` cue times on a jittered 10 s grid, strictly increasing.

    The jitter is bounded at +/-`SWITCH_CUE_JITTER_MS`, so consecutive cues are at least
    `SWITCH_CUE_INTERVAL_MS - 2 * SWITCH_CUE_JITTER_MS` apart and the ordering cannot
    invert. Bounded rather than free for exactly that reason: an unbounded jitter would
    occasionally place two cues inside one refractory interval and turn a correctly
    suppressed bounce into a recorded miss.
    """
    rng = _SplitMix64(seed)
    span = 2 * SWITCH_CUE_JITTER_MS + 1
    return [
        SWITCH_FIRST_CUE_MS + index * SWITCH_CUE_INTERVAL_MS + rng.below(span)
        - SWITCH_CUE_JITTER_MS
        for index in range(SWITCH_CUE_COUNT)
    ]


def generate_face_switch_task(seed: int | None = None) -> dict[str, Any]:
    seed = DEFAULT_SEEDS[FACE_SWITCH_TASK] if seed is None else seed
    cues = switch_cue_times_ms(seed)
    blocks: list[dict[str, Any]] = []
    for block_type in SWITCH_BLOCK_TYPES:
        blocks.append(
            {
                "block_id": block_type,
                "kind": "scored",
                "block_type": block_type,
                "duration_s": SWITCH_BLOCK_DURATION_S,
                "cue_times_ms": list(cues) if block_type == "deliberate" else [],
                "prompts": list(SPEAKING_PROMPTS) if block_type == "speaking" else [],
            }
        )
    doc = _envelope(
        FACE_SWITCH_TASK,
        seed,
        "Three five-minute blocks: rest, cued deliberate activations, and reading fixed "
        "public sentences aloud. The gesture under test is whichever one is configured -- "
        "the task is gesture-agnostic and the result records which it was. Keeping the "
        "blocks separate is what makes a false activation attributable to rest or to "
        "ordinary speech instead of averaging the two into one unusable rate.",
    )
    doc["blocks"] = blocks
    doc["scored_trials"] = sum(len(b["cue_times_ms"]) for b in blocks if b["kind"] == "scored")
    doc["privacy"] = _privacy()
    doc["limitations"] = [
        "Block order is fixed, not counterbalanced. Order effects are a study-protocol "
        "decision (#425), not something a fixture may quietly randomise away.",
        "Nothing here is a threshold. Cue spacing and block length shape what can be "
        "measured; they say nothing about what any setting should default to.",
    ]
    return doc


_GENERATORS = {
    GAZE_TASK: generate_gaze_task,
    HEAD_POINTER_TASK: generate_head_pointer_task,
    FACE_SWITCH_TASK: generate_face_switch_task,
}


def generate_task(task_id: str, seed: int | None = None) -> dict[str, Any]:
    """The task fixture for `task_id`, identical on every machine for a given seed."""
    if task_id not in _GENERATORS:
        raise KeyError(f"unknown task_id {task_id!r}; expected one of {TASK_IDS}")
    return _GENERATORS[task_id](seed)


def dump_task(doc: dict[str, Any]) -> str:
    """The canonical on-disk form: 2-space JSON, ASCII, one trailing newline.

    One spelling, so "the fixture changed" always means the task changed and never means
    somebody's editor reflowed it.
    """
    return json.dumps(doc, indent=2, ensure_ascii=True) + "\n"


# --- validation ---------------------------------------------------------------------

#: Keys whose value must be a plain integer wherever they appear. Floats are refused
#: rather than tolerated: they would make the checked-in bytes depend on repr formatting
#: and let a generator reach for trigonometry, which is how cross-platform byte stability
#: is lost.
_INTEGER_KEYS = frozenset(
    {
        "seed",
        "scored_trials",
        "trial_index",
        "target_id",
        "intended_target_id",
        "center_x",
        "center_y",
        "width",
        "height",
        "start_x",
        "start_y",
        "dx",
        "dy",
        "radius_permille",
        "target_width_permille",
        "duration_s",
        "cue_index",
    }
)
_INTEGER_LIST_KEYS = frozenset({"cue_times_ms"})


def _is_int(value: Any) -> TypeGuard[int]:
    """True for a whole number. `True` is an `int` in Python and is not a coordinate."""
    return isinstance(value, int) and not isinstance(value, bool)


def _integer_problems(node: Any, path: str) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}{key}"
            if key in _INTEGER_KEYS and not _is_int(value):
                out.append(
                    f"{here}: must be a whole number in per-mille/index units, got "
                    f"{type(value).__name__}. Floats are refused so the fixture's bytes "
                    f"cannot depend on the platform that wrote them."
                )
            elif key in _INTEGER_LIST_KEYS:
                if not isinstance(value, list) or not all(_is_int(v) for v in value):
                    out.append(f"{here}: must be a list of whole milliseconds.")
            out += _integer_problems(value, f"{here}.")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            out += _integer_problems(value, f"{path}{index}.")
    return out


def _rect_problems(rect: Any, path: str, minimum: int) -> list[str]:
    if not isinstance(rect, dict):
        return [f"{path}: expected a target object, got {type(rect).__name__}."]
    missing = [k for k in ("center_x", "center_y", "width", "height") if not _is_int(rect.get(k))]
    if missing:
        return [f"{path}: target is missing whole-number {', '.join(missing)}."]
    out: list[str] = []
    for edge_key in ("width", "height"):
        edge = int(rect[edge_key])
        if edge % 2:
            out.append(
                f"{path}.{edge_key}: must be even so the half-extent is an exact integer "
                f"(got {edge})."
            )
        if edge < minimum:
            out.append(
                f"{path}.{edge_key}: {edge} per-mille is below the task's floor of "
                f"{minimum}. This task deliberately uses large targets; a small one turns "
                f"it into a precision test and measures something else."
            )
    for centre_key, edge_key in (("center_x", "width"), ("center_y", "height")):
        half = int(rect[edge_key]) // 2
        low = int(rect[centre_key]) - half
        high = int(rect[centre_key]) + half
        if low < 0 or high > CANVAS_PERMILLE:
            out.append(
                f"{path}: extends from {low} to {high} on {centre_key[-1]}, outside the "
                f"0..{CANVAS_PERMILLE} canvas -- part of the target would be off-screen."
            )
    return out


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ax, ay = int(a["center_x"]), int(a["center_y"])
    bx, by = int(b["center_x"]), int(b["center_y"])
    return (
        abs(ax - bx) * 2 < int(a["width"]) + int(b["width"])
        and abs(ay - by) * 2 < int(a["height"]) + int(b["height"])
    )


def _gaze_problems(doc: dict[str, Any]) -> list[str]:
    out: list[str] = []
    targets = doc.get("targets")
    if not isinstance(targets, list) or len(targets) != GAZE_TARGET_COUNT:
        return [f"targets: expected a list of {GAZE_TARGET_COUNT} panes."]
    for index, pane in enumerate(targets):
        out += _rect_problems(pane, f"targets.{index}", MIN_GAZE_PANE_PERMILLE)
    if out:
        return out
    ids = [pane.get("target_id") for pane in targets]
    if sorted(i for i in ids if _is_int(i)) != list(range(1, GAZE_TARGET_COUNT + 1)):
        out.append(f"targets: pane ids must be 1..{GAZE_TARGET_COUNT}, got {ids}.")
    for i in range(len(targets)):
        for j in range(i + 1, len(targets)):
            if _overlap(targets[i], targets[j]):
                out.append(
                    f"targets.{i}/targets.{j}: panes overlap. A trial whose intended pane "
                    f"also covers another pane has no unambiguous correct answer."
                )
    scored = [b for b in doc.get("blocks", []) if isinstance(b, dict) and b.get("kind") == "scored"]
    expected_trials = GAZE_SCORED_ROUNDS * GAZE_TARGET_COUNT
    if len(scored) != 1:
        out.append(f"blocks: expected exactly one scored block, found {len(scored)}.")
    for block in scored:
        trials = block.get("trials")
        if not isinstance(trials, list):
            continue
        if len(trials) != expected_trials:
            # Checked explicitly because every per-pane rule below is vacuously satisfied
            # by an empty block: balance, no-repeat and round structure all hold for a
            # sequence of nothing.
            out.append(
                f"blocks.{block.get('block_id')}: version {TASK_VERSIONS[GAZE_TASK]} of this "
                f"task is {expected_trials} scored trials, not {len(trials)}. A shorter run "
                f"is a different denominator under the same task name."
            )
        asked = [t.get("intended_target_id") for t in trials if isinstance(t, dict)]
        counts = {i: asked.count(i) for i in range(1, GAZE_TARGET_COUNT + 1)}
        if len(set(counts.values())) != 1:
            out.append(
                f"blocks.{block.get('block_id')}: the sequence is unbalanced ({counts}). "
                f"Unequal pane counts make the correct-target rate a weighted average of "
                f"per-pane rates, which is not what it is reported as."
            )
        repeats = [i for i in range(1, len(asked)) if asked[i] == asked[i - 1]]
        if repeats:
            out.append(
                f"blocks.{block.get('block_id')}: pane repeats back-to-back at trial(s) "
                f"{repeats}. A repeat lets a tester score without re-acquiring the target."
            )
    return out


def _pointer_problems(doc: dict[str, Any]) -> list[str]:
    out: list[str] = []
    scored = [b for b in doc.get("blocks", []) if isinstance(b, dict) and b.get("kind") == "scored"]
    if len(scored) != len(POINTER_CONDITIONS):
        out.append(
            f"blocks: version {TASK_VERSIONS[HEAD_POINTER_TASK]} of this task runs "
            f"{len(POINTER_CONDITIONS)} scored width/radius conditions, not {len(scored)}."
        )
    for block in scored:
        trials = block.get("trials")
        # Named rather than implied: a block with no trials satisfies every ordering and
        # amplitude rule below without visiting a single target.
        if isinstance(trials, list) and len(trials) != POINTER_RING_POSITIONS:
            out.append(
                f"blocks.{block.get('block_id')}: a scored block visits all "
                f"{POINTER_RING_POSITIONS} ring positions, not {len(trials)}."
            )
    for block in doc.get("blocks", []):
        if not isinstance(block, dict):
            continue
        where = f"blocks.{block.get('block_id')}"
        targets = block.get("targets")
        if not isinstance(targets, list) or len(targets) != POINTER_RING_POSITIONS:
            out.append(f"{where}.targets: expected {POINTER_RING_POSITIONS} ring targets.")
            continue
        for index, target in enumerate(targets):
            out += _rect_problems(
                target, f"{where}.targets.{index}", MIN_POINTER_TARGET_PERMILLE
            )
        trials = block.get("trials")
        if not isinstance(trials, list) or not trials:
            out.append(f"{where}.trials: expected a non-empty list.")
            continue
        visited = [
            t["target_id"]
            for t in trials
            if isinstance(t, dict) and _is_int(t.get("target_id"))
        ]
        if len(visited) != len(trials):
            out.append(f"{where}.trials: every trial needs a whole-number target_id.")
        if len(set(visited)) != len(visited):
            out.append(
                f"{where}.trials: ring position visited twice ({visited}); each position "
                f"appears at most once per block so amplitudes stay balanced."
            )
        for index in range(1, len(visited)):
            gap = abs(visited[index] - visited[index - 1]) % POINTER_RING_POSITIONS
            if min(gap, POINTER_RING_POSITIONS - gap) < 3:
                out.append(
                    f"{where}.trials.{index}: moves to a neighbouring ring position. The "
                    f"alternating order exists so every movement crosses the centre; a "
                    f"short hop has a different amplitude from the rest of the block."
                )
        for index, trial in enumerate(trials):
            if not isinstance(trial, dict):
                continue
            target = next(
                (t for t in targets if t.get("target_id") == trial.get("target_id")), None
            )
            if target is None:
                out.append(f"{where}.trials.{index}.target_id: no such ring position.")
                continue
            for axis, centre_key in (("x", "center_x"), ("y", "center_y")):
                start = trial.get(f"start_{axis}")
                delta = trial.get("dx" if axis == "x" else "dy")
                if not _is_int(start) or not _is_int(delta):
                    out.append(f"{where}.trials.{index}: start_{axis} and its delta must be ints.")
                elif start + delta != int(target[centre_key]):
                    out.append(
                        f"{where}.trials.{index}: start_{axis} + delta is "
                        f"{start + delta} but the target centre is "
                        f"{target[centre_key]}. The recorded amplitude would not be the "
                        f"movement the tester was asked to make."
                    )
    return out


def _switch_problems(doc: dict[str, Any]) -> list[str]:
    out: list[str] = []
    blocks = doc.get("blocks")
    if not isinstance(blocks, list):
        return ["blocks: expected a list."]
    types = [b.get("block_type") for b in blocks if isinstance(b, dict)]
    if types != list(SWITCH_BLOCK_TYPES):
        out.append(
            f"blocks: expected block types {list(SWITCH_BLOCK_TYPES)} in that order, got "
            f"{types}. All three are required and the neutral and speaking blocks must "
            f"stay separately identifiable (EVALUATION.md)."
        )
    deliberate = [b for b in blocks if isinstance(b, dict) and b.get("block_type") == "deliberate"]
    for block in deliberate:
        cued = block.get("cue_times_ms")
        # Explicit, because every cue-ordering and cue-window rule below is satisfied by an
        # empty cue list -- a block that asks for nothing measures nothing.
        if isinstance(cued, list) and len(cued) != SWITCH_CUE_COUNT:
            out.append(
                f"blocks.{block.get('block_id')}: version "
                f"{TASK_VERSIONS[FACE_SWITCH_TASK]} of this task cues {SWITCH_CUE_COUNT} "
                f"deliberate activations, not {len(cued)}. Recall has that denominator."
            )
    for block in blocks:
        if not isinstance(block, dict):
            continue
        where = f"blocks.{block.get('block_id')}"
        duration = block.get("duration_s")
        cues = block.get("cue_times_ms")
        if not _is_int(duration) or duration <= 0:
            out.append(f"{where}.duration_s: expected a positive whole number of seconds.")
            continue
        if not isinstance(cues, list):
            out.append(f"{where}.cue_times_ms: expected a list.")
            continue
        if block.get("block_type") != "deliberate" and cues:
            out.append(
                f"{where}.cue_times_ms: a {block.get('block_type')!r} block cues nothing. "
                f"An activation during it is a false activation, and a cue would make that "
                f"unmeasurable."
            )
        if not all(_is_int(cue) for cue in cues):
            out.append(f"{where}.cue_times_ms: expected a list of whole milliseconds.")
            continue
        for index, cue in enumerate(cues):
            if not 0 < cue < duration * 1000:
                out.append(
                    f"{where}.cue_times_ms.{index}: {cue} ms falls outside the "
                    f"0..{duration * 1000} ms block."
                )
            if index and cue <= cues[index - 1]:
                out.append(f"{where}.cue_times_ms.{index}: cues must strictly increase.")
        prompts = block.get("prompts")
        if not isinstance(prompts, list):
            out.append(f"{where}.prompts: expected a list.")
        elif block.get("block_type") == "speaking":
            if not prompts:
                out.append(f"{where}.prompts: the speaking block needs sentences to read.")
            for index, prompt in enumerate(prompts):
                if prompt not in SPEAKING_PROMPTS:
                    out.append(
                        f"{where}.prompts.{index}: not one of the fixed public sentences. "
                        f"A tester's own words would put private speech in the record."
                    )
        elif prompts:
            out.append(f"{where}.prompts: only the speaking block reads sentences aloud.")
    return out


_TASK_CHECKS = {
    GAZE_TASK: _gaze_problems,
    HEAD_POINTER_TASK: _pointer_problems,
    FACE_SWITCH_TASK: _switch_problems,
}


def validate_task(doc: Any) -> list[str]:
    """Return every problem with one parsed task fixture, most structural first.

    Empty list means valid. Pure: no file, clock, camera or network is touched, and the
    document is not modified.
    """
    if not isinstance(doc, dict):
        return [f"<root>: expected a JSON object, got {type(doc).__name__}."]

    version = doc.get("fixture_schema_version")
    parts = version.split(".") if isinstance(version, str) else []
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return [
            f"fixture_schema_version: missing or malformed (got {version!r}); expected "
            f'"MAJOR.MINOR" with both parts numeric, e.g. "{FIXTURE_SCHEMA_VERSION}".'
        ]
    major = int(parts[0])
    if major != SUPPORTED_FIXTURE_MAJOR:
        return [
            f"fixture_schema_version: {version!r} has major version {major}; this reader "
            f"implements {SUPPORTED_FIXTURE_MAJOR}.x. A major bump changes or removes a "
            f"required field, so the fixture cannot be replayed safely."
        ]

    problems = forbidden_field_problems(doc)
    for field in REQUIRED_TASK_FIELDS:
        if field not in doc:
            problems.append(f"{field}: missing required field.")

    task_id = doc.get("task_id")
    if task_id not in TASK_IDS:
        problems.append(f"task_id: {task_id!r} is not one of {TASK_IDS}.")
    else:
        expected_version = TASK_VERSIONS[task_id]
        if doc.get("task_version") != expected_version:
            problems.append(
                f"task_version: {doc.get('task_version')!r} but this module implements "
                f"{expected_version!r} of {task_id!r}. Trial counts, target sizes and block "
                f"lengths are what a published number means; replaying a different version "
                f"under the same name would change the meaning silently."
            )
        if doc.get("feature") != TASK_FEATURES[task_id]:
            problems.append(
                f"feature: {task_id!r} feeds the {TASK_FEATURES[task_id]!r} metric family, "
                f"not {doc.get('feature')!r}."
            )
        if doc.get("records") != list(TASK_RECORDS[task_id]):
            problems.append(
                f"records: {task_id!r} records exactly {list(TASK_RECORDS[task_id])}. Every "
                f"field is a number, an index or an enum member; adding one is how a place "
                f"to put desktop text appears."
            )
        if doc.get("outcomes") != list(TASK_OUTCOMES[task_id]):
            problems.append(
                f"outcomes: expected {list(TASK_OUTCOMES[task_id])} for {task_id!r}."
            )
        if task_id in GEOMETRY_TASKS:
            for field in REQUIRED_GEOMETRY_FIELDS:
                if field not in doc:
                    problems.append(
                        f"{field}: missing, and {task_id!r} places targets on screen -- a "
                        f"coordinate without its unit is not a position."
                    )

    if "feature" in doc and doc["feature"] not in FEATURES:
        problems.append(f"feature: {doc['feature']!r} is not one of {FEATURES}.")
    if "geometry_units" in doc and doc["geometry_units"] != GEOMETRY_UNITS:
        problems.append(
            f"geometry_units: expected {GEOMETRY_UNITS!r}; pixels would bind the task to "
            f"one screen."
        )
    canvas = doc.get("canvas_permille")
    if "canvas_permille" in doc and (
        not isinstance(canvas, dict)
        or canvas.get("width") != CANVAS_PERMILLE
        or canvas.get("height") != CANVAS_PERMILLE
    ):
        problems.append(
            f"canvas_permille: expected width and height {CANVAS_PERMILLE} -- per-mille of "
            f"the logical display is 1000 by definition."
        )
    if "seed" in doc and (not _is_int(doc["seed"]) or int(doc["seed"]) < 0):
        problems.append("seed: expected a non-negative whole number; it is what makes the "
                        "order replayable.")
    records = doc.get("records")
    if "records" in doc:
        if not isinstance(records, list) or not records:
            problems.append("records: expected a non-empty list of field names.")
        elif len(set(records)) != len(records):
            problems.append(f"records: duplicate field name in {records}.")

    privacy = doc.get("privacy")
    if "privacy" in doc:
        if not isinstance(privacy, dict):
            problems.append(f"privacy: expected an object, got {type(privacy).__name__}.")
        else:
            for field in REQUIRED_PRIVACY_FIELDS:
                if field not in privacy:
                    problems.append(f"privacy.{field}: missing required field.")
            if "content_source" in privacy and privacy["content_source"] not in CONTENT_SOURCES:
                problems.append(
                    f"privacy.content_source: expected one of {CONTENT_SOURCES}. A task "
                    f"fixture describes generated content; a capture of a real screen needs "
                    f"its own ethics decision (ADR-v2-150 Rule 4)."
                )
            for flag in ("raw_media_retained", "contains_personal_identifiers"):
                if flag in privacy and privacy[flag] is not False:
                    problems.append(f"privacy.{flag}: must be false.")

    blocks = doc.get("blocks")
    if "blocks" in doc:
        if not isinstance(blocks, list) or not blocks:
            problems.append("blocks: expected a non-empty list.")
        else:
            seen: set[Any] = set()
            for index, block in enumerate(blocks):
                if not isinstance(block, dict):
                    problems.append(f"blocks.{index}: expected an object.")
                    continue
                block_id = block.get("block_id")
                if not isinstance(block_id, str) or not block_id:
                    problems.append(f"blocks.{index}.block_id: expected a non-empty string.")
                elif block_id in seen:
                    problems.append(
                        f"blocks.{index}.block_id: {block_id!r} is used twice; a result row "
                        f"could not say which block it came from."
                    )
                else:
                    seen.add(block_id)
                if block.get("kind") not in BLOCK_KINDS:
                    problems.append(f"blocks.{index}.kind: expected one of {BLOCK_KINDS}.")

    problems += _integer_problems(doc, "")

    if isinstance(blocks, list):
        counted = sum(
            len(block.get("trials", []) or []) + len(block.get("cue_times_ms", []) or [])
            for block in blocks
            if isinstance(block, dict) and block.get("kind") == "scored"
        )
        if "scored_trials" in doc and doc["scored_trials"] != counted:
            problems.append(
                f"scored_trials: says {doc['scored_trials']} but the scored blocks hold "
                f"{counted}. The denominator of every rate comes from this number."
            )

    if task_id in _TASK_CHECKS:
        problems += _TASK_CHECKS[task_id](doc)
    return problems


def check_task(doc: Any) -> None:
    """Raise `EyeEvalTaskError` listing every problem, or return None if valid."""
    problems = validate_task(doc)
    if problems:
        raise EyeEvalTaskError(
            f"{len(problems)} eye-control task fixture problem(s):\n  - "
            + "\n  - ".join(problems)
        )
