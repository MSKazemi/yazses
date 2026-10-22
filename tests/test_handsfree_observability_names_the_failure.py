"""Three hands-free failures that read identically had to be told apart — EYE-OBS-001 (#416).

Two acceptance criteria of #416 were not met by the rows that already existed:

* **A missing or blocked face model must be distinguishable from no camera.** The shared
  source wrapped "open the camera" and "build the face model" in one ``except`` and
  reported both as *the camera could not be opened*. A user behind a firewall -- whose
  camera was fine and whose one-time model download was refused -- was sent to look for
  the application holding their webcam. The source now records which stage failed
  (``FAILURE_*``), and every surface gives the fix that belongs to that stage.
* **Stale tracking must be distinguishable from a permission or backend failure.** A camera
  that stopped delivering frames left the source ``running`` with an old sample, and the
  face-switch row printed *tracking valid* for a sample no consumer would act on. The rows
  now apply the same age limit the consumers apply.

The spec's "backend/model name" (``design/specs/eye-shared-perception.md#observability``)
was also never surfaced, although the source knew it; it is now a name on the row.

Everything here is pure or driven by fakes: no camera, no model, no network.
"""

from __future__ import annotations

import dataclasses
import json
import types

import pytest

from yazses.config import Config, HandsfreeSafetyConfig
from yazses.core.daemon import Daemon
from yazses.handsfree.observability import (
    DEFAULT_STALE_AFTER_MS,
    FAILURE_REMEDIES,
    PERCEPTION_FAILED,
    PERCEPTION_RUNNING,
    HandsFreeFacts,
    Health,
    as_payload,
    facts_from_payload,
    health_rows,
    render_status_lines,
    stale_after_ms,
)
from yazses.handsfree.panel import merge_facts
from yazses.handsfree.probe import facts_from_config
from yazses.perception.source import (
    FAILURE_CAMERA,
    FAILURE_DEPENDENCY,
    FAILURE_KINDS,
    FAILURE_MODEL,
    FAILURE_PROCESSING,
    SharedPerceptionSource,
    SourceState,
    describe_open_failure,
)

# --------------------------------------------------------------------------- fakes


class _Capture:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.closes = 0

    def open(self) -> None:
        if self.error is not None:
            raise self.error

    def read(self) -> object | None:
        return None

    def close(self) -> None:
        self.closes += 1


class _Processor:
    name = "fake-landmarker"

    def process(self, frame: object, timestamp_s: float):  # pragma: no cover - not reached
        return None

    def close(self) -> None:
        pass


class _Worker:
    def join(self, timeout: float | None = None) -> None:
        pass

    def is_alive(self) -> bool:
        return False


def _source(*, capture_error: Exception | None = None, model_error: Exception | None = None):
    capture = _Capture(capture_error)

    def build_processor() -> _Processor:
        if model_error is not None:
            raise model_error
        return _Processor()

    source = SharedPerceptionSource(
        lambda: capture,
        build_processor,
        interval_s=0.0,
        clock=lambda: 1_000.0,
        spawn=lambda target, name: _Worker(),
    )
    return source, capture


def _cfg(**features: bool) -> Config:
    cfg = Config()
    for name, value in features.items():
        getattr(cfg, name).enabled = value
    return cfg


def _facts(cfg: Config, **overrides) -> HandsFreeFacts:
    return dataclasses.replace(facts_from_config(cfg, unwired=frozenset()), **overrides)


def _rows(facts: HandsFreeFacts) -> dict[str, object]:
    return {row.label: row for row in health_rows(facts)}


# ----------------------------------------------------- the source names the stage


def test_a_missing_dependency_is_named_by_module_whichever_stage_raised() -> None:
    error = ModuleNotFoundError("No module named 'mediapipe'", name="mediapipe")
    for stage in ("camera", "model"):
        kind, reason = describe_open_failure(stage, error)
        assert kind == FAILURE_DEPENDENCY
        assert reason.startswith("mediapipe is not installed"), reason
        assert "camera could not be opened" not in reason


def test_a_submodule_import_error_names_the_package_a_user_installs() -> None:
    error = ModuleNotFoundError("No module named 'mediapipe.tasks'", name="mediapipe.tasks")
    assert describe_open_failure("model", error)[1].startswith("mediapipe is not installed")


def test_an_import_error_with_no_module_name_still_says_dependency() -> None:
    kind, reason = describe_open_failure("model", ImportError("DLL load failed"))
    assert kind == FAILURE_DEPENDENCY
    assert "dependency is not installed" in reason


def test_a_model_that_cannot_be_fetched_is_not_reported_as_the_camera() -> None:
    kind, reason = describe_open_failure(
        "model", OSError("no address found for storage.googleapis.com")
    )
    assert kind == FAILURE_MODEL
    assert "face model could not be fetched or loaded" in reason
    assert "camera could not be opened" not in reason
    assert "storage.googleapis.com" in reason  # the cause itself is kept


def test_the_camera_wording_is_unchanged_from_before_the_split() -> None:
    """`status`, `doctor` and the panel already print it, and tests hold them agreeing."""
    kind, reason = describe_open_failure("camera", OSError("device busy"))
    assert kind == FAILURE_CAMERA
    assert reason == "the camera could not be opened (OSError: device busy)"


def test_a_reason_stays_bounded_however_long_the_exception_is() -> None:
    _, reason = describe_open_failure("model", RuntimeError("x" * 5_000))
    assert len(reason) < 400


@pytest.mark.parametrize(
    ("capture_error", "model_error", "kind", "needle"),
    [
        (OSError("device busy"), None, FAILURE_CAMERA, "camera could not be opened"),
        (None, OSError("no address found"), FAILURE_MODEL, "face model could not be fetched"),
        (None, ModuleNotFoundError("nope", name="mediapipe"), FAILURE_DEPENDENCY,
         "mediapipe is not installed"),
    ],
    ids=["camera", "model", "dependency"],
)
def test_the_real_source_records_which_stage_failed(capture_error, model_error, kind, needle):
    source, capture = _source(capture_error=capture_error, model_error=model_error)
    source.consumer("facegesture").start()
    status = source.status()
    assert status.state is SourceState.FAILED
    assert status.failure_kind == kind
    assert needle in status.failure_reason, status.failure_reason
    if model_error is not None:
        # The camera that did open is closed again, not left held by a failed session.
        assert capture.closes == 1


def test_a_healthy_open_reports_no_failure_kind_and_names_the_backend() -> None:
    source, _ = _source()
    source.consumer("facegesture").start()
    status = source.status()
    assert status.state is SourceState.RUNNING
    assert status.failure_kind == ""
    assert status.backend == "fake-landmarker"


def test_a_failure_kind_is_cleared_when_the_last_consumer_leaves() -> None:
    """A failure that is over must not be reported as a live one (the source's own rule)."""
    source, _ = _source(model_error=OSError("blocked"))
    lease = source.consumer("facegesture")
    lease.start()
    assert source.status().failure_kind == FAILURE_MODEL
    lease.stop()
    assert source.status().failure_kind == ""


# ------------------------------------------------------- every kind has its fix


def test_every_failure_kind_the_source_can_emit_has_a_remedy() -> None:
    """Derived from the producer, not a hand-written list: a new kind fails here."""
    assert set(FAILURE_REMEDIES) == set(FAILURE_KINDS)
    assert len(set(FAILURE_REMEDIES.values())) == len(FAILURE_REMEDIES), "two kinds, one fix"


def _failed(kind: str, reason: str) -> dict[str, object]:
    return _rows(_facts(
        _cfg(facegesture=True), camera_ready=True, perception_state=PERCEPTION_FAILED,
        perception_reason=reason, perception_failure_kind=kind,
    ))


def test_a_blocked_model_reads_differently_from_no_camera_and_from_a_busy_one() -> None:
    model = _failed(FAILURE_MODEL, "the camera opened, but the face model could not be "
                                   "fetched or loaded (OSError: blocked)")["Hands-free perception"]
    busy = _failed(FAILURE_CAMERA, "the camera could not be opened (OSError: busy)")[
        "Hands-free perception"]
    no_camera = _rows(_facts(_cfg(facegesture=True), camera_ready=False))[
        "Hands-free perception"]
    assert model.health is Health.FAULT and busy.health is Health.FAULT
    assert "model_path" in model.remedy and "camera itself is fine" in model.remedy
    assert "free the camera" in busy.remedy and "model" not in busy.remedy
    assert no_camera.health is Health.DORMANT
    assert len({model.detail, busy.detail, no_camera.detail}) == 3


def test_a_missing_dependency_remedy_points_at_the_row_that_names_the_package() -> None:
    row = _failed(FAILURE_DEPENDENCY, "mediapipe is not installed (ModuleNotFoundError)")[
        "Hands-free perception"]
    assert "mediapipe is not installed" in row.reason
    assert "camera extra" in row.remedy


def test_an_older_daemon_with_no_kind_gets_the_remedy_every_failure_had_before() -> None:
    row = _failed("", "the camera could not be opened (busy)")["Hands-free perception"]
    assert "fix the cause named above" in row.remedy
    unknown = _failed("from-the-future", "something new")["Hands-free perception"]
    assert unknown.remedy == row.remedy
    assert FAILURE_PROCESSING in FAILURE_REMEDIES


# --------------------------------------------------- stale is not "tracking valid"


def test_the_default_window_is_the_one_every_consumer_already_applies() -> None:
    """Not a new threshold. If one of these moves, decide what the rows should say."""
    from yazses.facegesture.shared import MAX_SAMPLE_AGE_S
    from yazses.headpointer.controller import DEFAULT_FRESHNESS_S

    assert DEFAULT_STALE_AFTER_MS == HandsfreeSafetyConfig().stale_after_ms
    assert DEFAULT_STALE_AFTER_MS == MAX_SAMPLE_AGE_S * 1000.0
    assert DEFAULT_STALE_AFTER_MS == DEFAULT_FRESHNESS_S * 1000.0


def test_the_watchdog_window_wins_when_it_is_known_and_usable() -> None:
    base = _facts(_cfg(facegesture=True))
    assert stale_after_ms(base) == DEFAULT_STALE_AFTER_MS
    assert stale_after_ms(dataclasses.replace(base, safety_window_ms=1500.0)) == 1500.0
    for broken in (0.0, -5.0, float("nan")):
        assert stale_after_ms(dataclasses.replace(base, safety_window_ms=broken)) == (
            DEFAULT_STALE_AFTER_MS
        ), broken


def _running(age_ms: float, **overrides) -> dict[str, object]:
    return _rows(_facts(
        _cfg(facegesture=True), camera_ready=True, perception_state=PERCEPTION_RUNNING,
        perception_channels=("face",), perception_age_ms=age_ms, perception_consumers=1,
        perception_backend="mediapipe", **overrides,
    ))


def test_a_fresh_sample_is_tracking_valid_and_names_the_backend() -> None:
    rows = _running(40.0)
    assert rows["Face switch"].health is Health.OK
    assert "tracking valid" in rows["Face switch"].reason
    assert rows["Hands-free perception"].health is Health.OK
    assert "backend mediapipe" in rows["Hands-free perception"].reason


def test_a_sample_older_than_the_window_is_stale_not_valid() -> None:
    rows = _running(2_400.0)
    face, perception = rows["Face switch"], rows["Hands-free perception"]
    assert face.health is Health.DEGRADED
    assert "tracking invalid" in face.reason and "2400 ms" in face.reason
    assert "tracking valid" not in face.reason
    assert perception.health is Health.DEGRADED
    assert perception.reason.startswith("stale"), perception.reason
    assert "500 ms" in perception.reason
    assert "stopped delivering frames" in perception.remedy


def test_the_configured_window_is_what_decides_stale() -> None:
    assert _running(1_000.0, safety_window_ms=1_500.0)["Face switch"].health is Health.OK
    assert _running(1_000.0)["Face switch"].health is Health.DEGRADED


def test_stale_failed_and_refused_are_three_different_answers() -> None:
    """The acceptance criterion as one comparison: three causes, three words, three fixes."""
    stale = _running(2_400.0)["Hands-free perception"]
    failed = _failed(FAILURE_CAMERA, "the camera could not be opened (busy)")[
        "Hands-free perception"]
    refused = _rows(_facts(_cfg(facegesture=True), camera_ready=False))["Hands-free perception"]
    words = {stale.reason.split(" ")[0], failed.reason.split(" ")[0],
             refused.reason.split(" ")[0]}
    assert words == {"stale", "failed", "dormant"}
    assert len({stale.remedy, failed.remedy, refused.remedy}) == 3


# ------------------------------------------- the new facts reach every surface


def test_the_new_fields_round_trip_through_the_status_wire() -> None:
    facts = _facts(_cfg(facegesture=True), perception_state=PERCEPTION_FAILED,
                   perception_backend="mediapipe", perception_failure_kind=FAILURE_MODEL)
    back = facts_from_payload(json.loads(json.dumps(as_payload(facts))))
    assert back is not None
    assert back.perception_backend == "mediapipe"
    assert back.perception_failure_kind == FAILURE_MODEL


def test_an_older_daemon_without_the_fields_reads_as_not_known() -> None:
    payload = as_payload(_facts(_cfg(facegesture=True)))
    assert payload is not None
    payload.pop("perception_backend")
    payload.pop("perception_failure_kind")
    back = facts_from_payload(payload)
    assert back is not None
    assert (back.perception_backend, back.perception_failure_kind) == ("", "")


def test_doctor_keeps_what_only_the_daemon_knows() -> None:
    """`doctor` merges the daemon's facts over its own; a field it dropped was a row lost."""
    static = _facts(_cfg(facegesture=True), camera_ready=True)
    live = dataclasses.replace(
        static, perception_backend="mediapipe", perception_failure_kind=FAILURE_MODEL,
        switch_actions=("select: last refused (the Head-Pointer is paused)",),
    )
    merged = merge_facts(static, live)
    assert merged.perception_backend == "mediapipe"
    assert merged.perception_failure_kind == FAILURE_MODEL
    assert merged.switch_actions == live.switch_actions
    assert "Face switch actions" in _rows(merged)


def test_status_prints_the_model_failure_with_its_own_fix() -> None:
    facts = _facts(_cfg(facegesture=True), perception_state=PERCEPTION_FAILED,
                   perception_reason="the camera opened, but the face model could not be "
                                     "fetched or loaded (OSError: blocked)",
                   perception_failure_kind=FAILURE_MODEL)
    text = "\n".join(render_status_lines(as_payload(facts)))
    assert "face model could not be fetched" in text
    assert "model_path" in text


# --------------------------------------------------------------- the daemon side


class _SharedStandIn:
    def __init__(self, status) -> None:
        self._status = status

    def status(self):
        return self._status


def _daemon_with(source_status) -> types.SimpleNamespace:
    cfg = Config()
    cfg.gaze.enabled = True
    return types.SimpleNamespace(
        _config=cfg,
        _gaze_targeter=object(),
        _extra_activations=[],
        _perception=_SharedStandIn(source_status),
        _gaze_on_shared_source=True,
    )


def test_the_daemon_publishes_the_failure_kind_of_a_failed_source() -> None:
    source, _ = _source(model_error=OSError("no address found"))
    source.consumer("gaze").start()
    payload = Daemon._handsfree_payload(_daemon_with(source.status()))
    assert payload is not None
    assert payload["perception_state"] == "failed"
    assert payload["perception_failure_kind"] == FAILURE_MODEL
    assert "face model" in str(payload["perception_reason"])


def test_the_daemon_publishes_the_backend_name_of_a_running_source() -> None:
    source, _ = _source()
    source.consumer("gaze").start()
    payload = Daemon._handsfree_payload(_daemon_with(source.status()))
    assert payload is not None
    assert payload["perception_state"] == "running"
    assert payload["perception_backend"] == "fake-landmarker"
    assert payload["perception_failure_kind"] == ""
