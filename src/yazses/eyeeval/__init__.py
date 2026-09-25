"""Eye/camera-control evaluation: the result schema, the tasks it describes, and the runner.

Dormant by design. Nothing in the daemon imports this package, so an existing install is
unchanged; it exists so a contributor can run a scripted eye-control test and hand back a
number somebody else can interpret. Pure stdlib -- no camera, no network, and no file
written except the result the tester asked for.

Four parts that only mean something together. `yazses.eyeeval.schema` is the envelope a
finished result arrives in; `yazses.eyeeval.tasks` is the task that produced it, frozen
hard enough that two machines ran the same experiment. A result without its task version is
a number without a question. `yazses.eyeeval.provenance` reads the safe machine facts that
make the number interpretable -- and none of the ones ADR-v2-150 promises never to collect.
`yazses.eyeeval.runner` is the part in the middle: it turns one task and a set of trial
outcomes into a validated result, checks it for leaks *before* the write, and is what
`yazses eye-eval` runs.

See `design/eye-control/METRICS.md` for the envelope this encodes and
`design/eye-control/EVALUATION.md` for where in the E0-E7 ladder it is checked.
"""

from yazses.eyeeval.provenance import (
    LocalIdentifiers,
    Provenance,
    local_identifiers,
)
from yazses.eyeeval.provenance import collect as collect_provenance
from yazses.eyeeval.runner import (
    GENERATOR,
    UNUSABLE_OUTCOMES,
    VERDICTS,
    EyeEvalRunError,
    build_result,
    check_records,
    completeness_verdict,
    dump_result,
    expected_scored_trials,
    privacy_problems,
    safe_settings,
    summarize,
    synthetic_records,
    tally,
    write_result,
)
from yazses.eyeeval.schema import (
    CAMERA_CLASSES,
    CAPTURE_MODES,
    DATA_CLASS_FOR_MODE,
    FEATURES,
    FORBIDDEN_FIELD_TOKENS,
    MISSING_REASONS,
    REQUIRED_SECTIONS,
    REQUIRED_TOP_LEVEL,
    SCHEMA_VERSION,
    SESSION_TYPES,
    STUDY_MODES,
    SUPPORTED_MAJOR,
    EyeEvalSchemaError,
    check_result,
    forbidden_field_problems,
    validate_result,
)
from yazses.eyeeval.tasks import (
    BLOCK_KINDS,
    CANVAS_PERMILLE,
    CONTENT_SOURCES,
    DEFAULT_SEEDS,
    FACE_SWITCH_TASK,
    FIXTURE_FILENAMES,
    FIXTURE_SCHEMA_VERSION,
    GAZE_TASK,
    GEOMETRY_TASKS,
    GEOMETRY_UNITS,
    HEAD_POINTER_TASK,
    SPEAKING_PROMPTS,
    SUPPORTED_FIXTURE_MAJOR,
    SWITCH_BLOCK_TYPES,
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

__all__ = [
    "BLOCK_KINDS",
    "CAMERA_CLASSES",
    "CANVAS_PERMILLE",
    "CAPTURE_MODES",
    "CONTENT_SOURCES",
    "DATA_CLASS_FOR_MODE",
    "DEFAULT_SEEDS",
    "FACE_SWITCH_TASK",
    "FEATURES",
    "FIXTURE_FILENAMES",
    "FIXTURE_SCHEMA_VERSION",
    "FORBIDDEN_FIELD_TOKENS",
    "GAZE_TASK",
    "GENERATOR",
    "GEOMETRY_TASKS",
    "GEOMETRY_UNITS",
    "HEAD_POINTER_TASK",
    "MISSING_REASONS",
    "REQUIRED_SECTIONS",
    "REQUIRED_TOP_LEVEL",
    "SCHEMA_VERSION",
    "SESSION_TYPES",
    "SPEAKING_PROMPTS",
    "STUDY_MODES",
    "SUPPORTED_FIXTURE_MAJOR",
    "SUPPORTED_MAJOR",
    "SWITCH_BLOCK_TYPES",
    "TASK_FEATURES",
    "TASK_IDS",
    "TASK_OUTCOMES",
    "TASK_RECORDS",
    "TASK_VERSIONS",
    "UNUSABLE_OUTCOMES",
    "VERDICTS",
    "EyeEvalRunError",
    "EyeEvalSchemaError",
    "EyeEvalTaskError",
    "LocalIdentifiers",
    "Provenance",
    "build_result",
    "check_records",
    "check_result",
    "check_task",
    "collect_provenance",
    "completeness_verdict",
    "dump_result",
    "dump_task",
    "expected_scored_trials",
    "forbidden_field_problems",
    "generate_task",
    "local_identifiers",
    "privacy_problems",
    "safe_settings",
    "summarize",
    "synthetic_records",
    "tally",
    "validate_result",
    "validate_task",
    "write_result",
]
