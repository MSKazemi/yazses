"""ADR-028 §5: one pure function gives every surface a pack-backed feature's state, and
*waiting for add-on* never reads as `on`."""
from __future__ import annotations

import json

import pytest

from tests.packs_fixtures import OTHER_BUILD_ID, entry_dict, index_dict
from yazses.packs.layout import build_dir_name
from yazses.packs.manifest import parse_index
from yazses.packs.policy import Capability
from yazses.packs.state import (
    DAMAGED,
    NOT_INSTALLED,
    OK,
    STALE,
    UNAVAILABLE,
    TreeFact,
    claimed_dirs,
    dump_state,
    empty_state,
    feature_status,
    installed_elsewhere,
    mark_started_ok,
    parse_state,
    record_install,
    record_result,
    remove_pack,
    started_ok,
)

INDEX = parse_index(json.dumps(index_dict()))
ENTRY = INDEX.packs[0]
CAPABLE = Capability(True)


def _status(*, config_on=True, capability=CAPABLE, index=INDEX, trees=None, doc=None,
            slug="stt-parakeet", index_error=None):
    return feature_status(
        slug, config_on=config_on, capability=capability, index=index,
        index_error=index_error, trees=trees or {}, doc=doc or empty_state(),
    )


def _stale_doc():
    comp = build_dir_name(OTHER_BUILD_ID, {})
    return record_install(empty_state(), component=comp, build_id=OTHER_BUILD_ID,
                          app_version="2.43.0", entry=ENTRY, at=1.0)


CASES = {
    "installed": dict(trees={"parakeet": TreeFact("ok")}),
    "not installed": dict(),
    "needs download for this version": dict(doc=_stale_doc()),
    "damaged": dict(trees={"parakeet": TreeFact("damaged", "site/x.dll is missing")}),
    "unavailable: channel": dict(capability=Capability(False, "not here", "unsupported")),
    "unavailable: elevated": dict(capability=Capability(False, "admin", "elevated")),
    "unavailable: no index": dict(index=None, index_error="missing"),
    "unavailable: no pack": dict(slug="gaze"),
}
EXPECTED = {
    "installed": OK,
    "not installed": NOT_INSTALLED,
    "needs download for this version": STALE,
    "damaged": DAMAGED,
    "unavailable: channel": UNAVAILABLE,
    "unavailable: elevated": UNAVAILABLE,
    "unavailable: no index": UNAVAILABLE,
    "unavailable: no pack": UNAVAILABLE,
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_state_from_a_fixture(case: str) -> None:
    assert _status(**CASES[case]).state == EXPECTED[case]


@pytest.mark.parametrize("case", sorted(CASES))
def test_waiting_for_an_add_on_never_reads_as_on(case: str) -> None:
    """The rule the whole state machine exists to keep."""
    status = _status(**CASES[case])
    if status.state != OK:
        assert not status.reads_on
        assert status.label != "on"
    else:
        assert status.reads_on and status.label == "on"


def test_off_reads_off_in_every_state() -> None:
    for case in CASES.values():
        status = _status(config_on=False, **case)
        assert not status.reads_on
        assert status.label != "on"


def test_messages_name_the_next_step_and_the_price() -> None:
    assert "0.3 MB download, 1.2 MB on disk" in _status().message
    stale = _status(doc=_stale_doc())
    assert "built for 2.43.0" in stale.message and "packs install parakeet" in stale.message
    damaged = _status(trees={"parakeet": TreeFact("damaged", "site/x.dll is missing")})
    assert "Reinstall" in damaged.message and "x.dll" in damaged.message
    assert damaged.label == "damaged — reinstall"


def test_state_json_round_trips_and_tolerates_garbage() -> None:
    doc = record_install(empty_state(), component="b-aaaaaaaaaaaa", build_id="sha256:" + "a" * 64,
                         app_version="2.44.0", entry=ENTRY, at=5.0)
    doc = record_result(doc, "parakeet", ok=True, step="done", message="ok", at=5.0)
    doc = mark_started_ok(doc, "sha256:" + "a" * 64)
    again = parse_state(dump_state(doc))
    assert again == doc
    assert claimed_dirs(again) == {"b-aaaaaaaaaaaa": "sha256:" + "a" * 64}
    assert started_ok(again, "sha256:" + "a" * 64)
    for garbage in (None, "", "{", "[]", json.dumps({"format": 9}), json.dumps({"format": 1,
                    "builds": [], "started_ok": "x"})):
        assert parse_state(garbage)["builds"] == {}


def test_installed_elsewhere_names_the_newest_other_build() -> None:
    doc = _stale_doc()
    newer = entry_dict()
    newer_entry = parse_index(json.dumps(index_dict(newer))).packs[0]
    doc = record_install(doc, component="b-cccccccccccc", build_id="sha256:" + "c" * 64,
                         app_version="2.43.5", entry=newer_entry, at=9.0)
    assert installed_elsewhere(doc, "parakeet", INDEX.base_build_id) == "2.43.5"
    assert installed_elsewhere(doc, "parakeet", "sha256:" + "c" * 64) == "2.43.0"
    assert installed_elsewhere(empty_state(), "parakeet", INDEX.base_build_id) is None


def test_remove_pack_drops_an_empty_build() -> None:
    doc = _stale_doc()
    comp = next(iter(doc["builds"]))
    assert remove_pack(doc, comp, "parakeet")["builds"] == {}
    assert doc["builds"], "the input must not be mutated"
