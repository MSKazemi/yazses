"""The store-listing drift detector.

The published Snap Store page drifted from snapcraft.yaml for a month across
three releases and nothing in the repository could see it, because nothing in
the repository ever read it. These tests cover the comparison logic; they never
touch the network, so the store being down cannot redden CI.
"""

from __future__ import annotations

import importlib.util
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/check-store-listing.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("check_store_listing", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(sys.platform == "win32", reason="Windows checkouts have no executable bit")
def test_the_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111, "should be runnable directly"


def test_it_parses_the_manifest_without_a_yaml_dependency(mod) -> None:
    """It must run from a bare checkout, before `uv sync`."""
    fields = mod.manifest_fields()
    assert fields["summary"]
    assert "Hold a key" in fields["description"]
    # The leading two-space YAML block indent must be stripped, or every line
    # would differ from the store's copy and the diff would be pure noise.
    assert not fields["description"].splitlines()[0].startswith("  ")


def test_a_matching_listing_passes(mod, monkeypatch, capsys) -> None:
    local = mod.manifest_fields()
    monkeypatch.setattr(mod, "store_fields", lambda name, timeout: dict(local))
    monkeypatch.setattr(mod.sys, "argv", ["check-store-listing.py"])
    assert mod.main() == 0
    assert "matches" in capsys.readouterr().out


def test_a_drifted_summary_fails(mod, monkeypatch) -> None:
    local = mod.manifest_fields()
    monkeypatch.setattr(
        mod, "store_fields",
        lambda name, timeout: {**local, "summary": "something else entirely"},
    )
    monkeypatch.setattr(mod.sys, "argv", ["check-store-listing.py"])
    assert mod.main() == 1


def test_whitespace_alone_is_not_drift(mod, monkeypatch) -> None:
    """The store reflows text; a newline difference must not cry wolf."""
    local = mod.manifest_fields()
    reflowed = {
        "summary": local["summary"],
        "description": local["description"].replace("\n", "  ") + "\n\n",
    }
    monkeypatch.setattr(mod, "store_fields", lambda name, timeout: reflowed)
    monkeypatch.setattr(mod.sys, "argv", ["check-store-listing.py"])
    assert mod.main() == 0


@pytest.mark.parametrize(
    "phrase",
    [
        "INSTALL — all four commands are required.",
        "yazses setup — provisions the rest, and re-checks both interfaces.",
        "nothing leaves your machine",
        "stable is amd64 today",
    ],
)
def test_each_forbidden_construction_is_caught(mod, monkeypatch, phrase: str) -> None:
    """Each of these was live on the page on 2026-09-13, verbatim."""
    local = mod.manifest_fields()
    monkeypatch.setattr(
        mod, "store_fields",
        lambda name, timeout: {**local, "description": local["description"] + f"\n{phrase}"},
    )
    monkeypatch.setattr(mod.sys, "argv", ["check-store-listing.py"])
    assert mod.main() == 1


def test_our_own_corrective_sentence_does_not_trip_it(mod, monkeypatch) -> None:
    """"`yazses setup` is not an installation step" is the FIX, not the bug.

    A detector that fires on the correction as well as the mistake gets muted,
    and a muted detector is why the page drifted for a month unnoticed.
    """
    local = mod.manifest_fields()
    assert "yazses setup" in local["description"], "precondition: we do mention it"
    monkeypatch.setattr(mod, "store_fields", lambda name, timeout: dict(local))
    monkeypatch.setattr(mod.sys, "argv", ["check-store-listing.py"])
    assert mod.main() == 0


def test_the_manifest_itself_trips_nothing(mod) -> None:
    """The denylist must describe the store's mistakes, not forbid our own text.

    If a phrase we deliberately ship trips the check, the detector cries wolf on
    every run and gets ignored -- which is how the drift survived in the first
    place.
    """
    local = mod.manifest_fields()
    blob = mod._norm(local["description"] + " " + local["summary"])
    import re as _re
    tripped = [p for p, _ in mod.FORBIDDEN if _re.search(p, blob)]
    assert not tripped, f"snapcraft.yaml itself trips the denylist: {tripped}"


def test_an_unreachable_store_exits_2_not_0(mod, monkeypatch, capsys) -> None:
    """"Could not check" must never read as "in sync".

    A watcher that reports success when it could not reach its target is the
    exact failure it was built to prevent.
    """
    def boom(name, timeout):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(mod, "store_fields", boom)
    monkeypatch.setattr(mod.sys, "argv", ["check-store-listing.py"])
    assert mod.main() == 2
    assert "COULD NOT CHECK" in capsys.readouterr().err


def test_a_timeout_also_exits_2(mod, monkeypatch) -> None:
    def boom(name, timeout):
        raise TimeoutError

    monkeypatch.setattr(mod, "store_fields", boom)
    monkeypatch.setattr(mod.sys, "argv", ["check-store-listing.py"])
    assert mod.main() == 2
