"""Eye/camera-control evaluation artifacts: the result schema and its validator.

Import-light and dormant by design. Nothing in the daemon imports this package, so an
existing install is unchanged; it exists for the evaluation runner (#423) and the
non-hardware CI matrix (#424) to build on. Pure stdlib -- no camera, no file I/O, no
network.

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
    validate_result,
)

__all__ = [
    "CAMERA_CLASSES",
    "CAPTURE_MODES",
    "DATA_CLASS_FOR_MODE",
    "FEATURES",
    "FORBIDDEN_FIELD_TOKENS",
    "MISSING_REASONS",
    "REQUIRED_SECTIONS",
    "REQUIRED_TOP_LEVEL",
    "SCHEMA_VERSION",
    "SESSION_TYPES",
    "STUDY_MODES",
    "SUPPORTED_MAJOR",
    "EyeEvalSchemaError",
    "check_result",
    "validate_result",
]
