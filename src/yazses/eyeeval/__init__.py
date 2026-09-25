"""Eye/camera-control evaluation artifacts: the result schema, and the tasks it describes.

Import-light and dormant by design. Nothing in the daemon imports this package, so an
existing install is unchanged; it exists for the evaluation runner (#423) and the
non-hardware CI matrix (#424) to build on. Pure stdlib -- no camera, no file I/O, no
network.

Two halves that only mean something together. `yazses.eyeeval.schema` is the envelope a
finished result arrives in; `yazses.eyeeval.tasks` is the task that produced it, frozen
hard enough that two machines ran the same experiment. A result without its task version is
a number without a question.

See `design/eye-control/METRICS.md` for the envelope this encodes and
`design/eye-control/EVALUATION.md` for where in the E0-E7 ladder it is checked.
"""

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
    "EyeEvalSchemaError",
    "EyeEvalTaskError",
    "check_result",
    "check_task",
    "dump_task",
    "forbidden_field_problems",
    "generate_task",
    "validate_result",
    "validate_task",
]
