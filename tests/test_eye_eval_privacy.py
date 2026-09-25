"""No hostname, login name, home directory or email can reach an eye-eval result.

`design/eye-control/DATA_SHARING.md` lists those under "never required in a public issue",
and ADR-v2-150 Rule 4 makes it a programme promise rather than a habit. A promise needs two
different guards, because they fail differently:

**Structural.** The envelope has no field to put one in, and
`schema.forbidden_field_problems` refuses a document that invents one at any depth. A field
that cannot exist cannot leak, and nothing has to remember anything.

**A value sweep.** A field that *should* hold a CPU model can still be handed a path. So
`runner.privacy_problems` walks the finished document, and `runner.write_result` runs it
**before** the file exists.

The risk with a guard like this is that it is vacuous -- a sweep with a broken matcher
reports a clean bill of health, which is the worst possible failure for a privacy check.
So every test below that asserts "clean" is paired with a mutation that must make the same
sweep fail, and `test_the_sweep_is_not_vacuous` mutates the *real* document produced on
*this* machine with *this* machine's real identifiers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yazses.eyeeval import (
    FORBIDDEN_FIELD_TOKENS,
    GAZE_TASK,
    EyeEvalRunError,
    LocalIdentifiers,
    build_result,
    collect_provenance,
    dump_result,
    forbidden_field_problems,
    generate_task,
    local_identifiers,
    privacy_problems,
    synthetic_records,
    validate_result,
    write_result,
)

_FAKE_IDS = LocalIdentifiers(
    hostname="thinkpad-of-someone",
    usernames=("evelyn",),
    home_paths=("/home/evelyn",),
)


def _real_result() -> dict[str, object]:
    """A document built from this machine's real provenance -- the thing that ships."""
    task = generate_task(GAZE_TASK)
    return build_result(
        task=task,
        records=synthetic_records(task),
        provenance=collect_provenance(),
        study_mode="synthetic",
        timestamp="2026-09-25T00:00:00+00:00",
        camera_class="none",
        capture_mode="synthetic_replay",
        records_source="synthetic",
    )


# --- the document this machine actually produces -----------------------------------------


def test_a_real_run_on_this_machine_leaks_nothing() -> None:
    """The positive claim. `test_the_sweep_is_not_vacuous` is what makes it mean something."""
    doc = _real_result()
    assert validate_result(doc) == []
    assert privacy_problems(doc, local_identifiers()) == []


def test_the_sweep_is_not_vacuous() -> None:
    """Put this machine's own identifiers into the real document; the sweep must object.

    Without this, a matcher that silently matched nothing would make the test above pass
    on every machine forever. Each identifier is injected on its own, so a sweep that
    happened to catch only one of the three cannot hide behind the others.
    """
    ids = local_identifiers()
    injections: list[tuple[str, str]] = []
    if len(ids.hostname) >= 3:
        injections.append(("hostname", ids.hostname))
    for name in ids.usernames:
        if len(name) >= 3:
            injections.append(("login name", name))
            break
    for home in ids.home_paths:
        if len(home) >= 3:
            injections.append(("home directory", home))
            break
    assert injections, (
        "this machine reports no hostname, login name or home directory at all, so the "
        "sweep cannot be exercised here — that is an environment problem, not a pass"
    )
    for label, value in injections:
        doc = _real_result()
        doc["config"]["settings"]["gaze.note"] = f"collected on {value}"  # type: ignore[index]
        problems = privacy_problems(doc, ids)
        assert problems, f"the sweep did not notice this machine's {label}"
        assert "config.settings" in problems[0]


def test_nothing_is_written_when_the_sweep_objects(tmp_path: Path) -> None:
    """The order is the whole feature: a leak must not reach the disk even once."""
    doc = _real_result()
    doc["machine"]["cpu_model"] = "CPU in /home/evelyn/box"  # type: ignore[index]
    target = tmp_path / "result.json"
    with pytest.raises(EyeEvalRunError) as caught:
        write_result(doc, target, identifiers=_FAKE_IDS)
    assert not target.exists(), "the file was created before the sweep ran"
    assert "home directory" in str(caught.value)


# --- the generic patterns, on any machine -------------------------------------------------


@pytest.mark.parametrize(
    "leaked",
    [
        "/home/evelyn/Documents",
        "/Users/evelyn/Library",
        r"C:\Users\evelyn\AppData",
        "evelyn@example.org",
    ],
)
def test_a_path_or_an_address_is_caught_without_knowing_the_machine(leaked: str) -> None:
    """These fire with no `identifiers` at all, which is what protects a host whose login
    name could not be read -- a daemon started from a unit file has no `$USER`."""
    doc = _real_result()
    doc["protocol"]["protocol_id"] = leaked  # type: ignore[index]
    problems = privacy_problems(doc)
    assert problems and "protocol.protocol_id" in problems[0], problems


def test_a_leak_is_found_wherever_it_sits() -> None:
    """Nested lists and dicts alike: a display entry is a list member, not a top-level key."""
    doc = _real_result()
    doc["display"]["displays"][0]["label"] = "/home/evelyn/screen"  # type: ignore[index]
    problems = privacy_problems(doc, _FAKE_IDS)
    assert any("display.displays.0.label" in p for p in problems), problems


def test_a_key_named_after_the_login_is_caught_too() -> None:
    """A key name leaks exactly as well as a value, and the schema's token list cannot
    know one particular person's name."""
    doc = _real_result()
    doc["config"]["settings"]["evelyn"] = 1  # type: ignore[index]
    assert privacy_problems(doc, _FAKE_IDS)


# --- the structural half ------------------------------------------------------------------


@pytest.mark.parametrize("token", ["hostname", "username", "window_title", "screenshot", "landmark"])
def test_a_field_the_programme_promised_not_to_collect_fails_the_schema(token: str) -> None:
    doc = _real_result()
    doc["machine"][token] = "anything at all"  # type: ignore[index]
    assert any(token in p for p in validate_result(doc))


def test_no_field_name_in_a_clean_result_trips_the_token_list() -> None:
    assert forbidden_field_problems(_real_result()) == []
    assert FORBIDDEN_FIELD_TOKENS, "an empty token list would make the line above vacuous"


def test_the_serialised_document_names_no_forbidden_token() -> None:
    """Read the bytes, not the object: this is what a tester pastes into an issue."""
    text = dump_result(_real_result())
    parsed = json.loads(text)
    assert parsed == json.loads(text)
    for token in FORBIDDEN_FIELD_TOKENS:
        assert f'"{token}"' not in text, token


# --- the identifier comparison is deliberately case-sensitive ------------------------------


def test_a_cloud_image_whose_login_matches_its_distribution_is_not_flagged() -> None:
    """`ubuntu` the account and `Ubuntu` the distribution are different strings.

    A default cloud or container image gives them the same word, and `machine.os_name`
    legitimately carries the capitalised form. A case-insensitive compare would fire on
    every correct result produced on such a host, and a guard that fires on a correct
    document is one people learn to ignore (ADR-021).
    """
    doc = _real_result()
    doc["machine"]["os_name"] = "Ubuntu"  # type: ignore[index]
    doc["machine"]["os_version"] = "24.04"  # type: ignore[index]
    ids = LocalIdentifiers(hostname="ubuntu", usernames=("ubuntu",), home_paths=("/home/ubuntu",))
    assert privacy_problems(doc, ids) == []
    # ...and the lowercase form still cannot get through, because it arrives as a path.
    doc["machine"]["cpu_model"] = "reported by /home/ubuntu/probe"  # type: ignore[index]
    assert privacy_problems(doc, ids)


def test_a_short_identifier_is_not_matched() -> None:
    """A two-letter login occurs inside ordinary words; matching it would make the sweep
    fire on a CPU model, and a dismissed guard catches nothing (ADR-021)."""
    doc = _real_result()
    assert privacy_problems(doc, LocalIdentifiers(hostname="ab", usernames=("pc",))) == []
