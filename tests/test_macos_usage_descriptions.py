"""Every macOS permission string the app needs must be declared, and checked.

Two lists have to agree and nothing made them:

* `packaging/macos/yazses.spec` — the `NS*UsageDescription` keys baked into the
  built `.app`. Without the string for a service, macOS may refuse that service
  **without ever showing a prompt**, which is how #182 presented: Accessibility
  granted, the hotkey dead, and no dialog to answer.
* `scripts/inspect-dmg.py::PLIST_KEYS` — the keys the released `.dmg` is actually
  inspected for. A key absent from *that* tuple is not checked at all, so the
  inspector reports a clean bundle while the string is missing.

The second is the nastier one, because it fails silently in the direction of
"looks fine". This file derives the required set from the spec rather than
restating it, so a permission added tomorrow is covered the day it is added --
a hand-written copy of a list is the defect this is guarding against, not the
cure for it.

⚠ This proves the keys are *declared*. That they survive into the built bundle is
what `inspect-dmg.py` proves, and it needs a real `.dmg`.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "packaging" / "macos" / "yazses.spec"
INSPECTOR = REPO / "scripts" / "inspect-dmg.py"


def _spec_info_plist() -> dict[str, ast.expr]:
    """The spec's `info_plist=` dict, read as source.

    Not imported: the spec runs under PyInstaller and pulls in the whole app.
    """
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "info_plist":
            assert isinstance(node.value, ast.Dict)
            return {
                k.value: v
                for k, v in zip(node.value.keys, node.value.values)
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
    raise AssertionError("no info_plist= in the macOS spec")


def _inspector_plist_keys() -> set[str]:
    """`PLIST_KEYS` out of the inspector, without importing it (it is a script
    with a hyphen in its name)."""
    tree = ast.parse(INSPECTOR.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "PLIST_KEYS" for t in node.targets
        ):
            assert isinstance(node.value, ast.Tuple)
            return {
                e.value for e in node.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            }
    raise AssertionError("no PLIST_KEYS in scripts/inspect-dmg.py")


def _usage_description_keys(keys) -> set[str]:
    return {k for k in keys if re.fullmatch(r"NS\w+UsageDescription", k)}


# ---- the guard is not vacuous -------------------------------------------


def test_the_spec_declares_some_usage_descriptions() -> None:
    """A guard that iterates is green over an empty set. If the extraction breaks,
    every assertion below passes while checking nothing."""
    declared = _usage_description_keys(_spec_info_plist())
    assert len(declared) >= 2, f"expected several NS*UsageDescription keys, got {declared}"


# ---- the two lists agree -------------------------------------------------


def test_every_declared_usage_description_is_inspected() -> None:
    declared = _usage_description_keys(_spec_info_plist())
    missing = sorted(declared - _inspector_plist_keys())
    assert not missing, (
        f"{missing} are in the app bundle but scripts/inspect-dmg.py never looks for "
        "them, so a released .dmg missing the string would inspect clean. Add them to "
        "PLIST_KEYS."
    )


def test_the_inspector_does_not_check_for_a_string_the_app_never_declares() -> None:
    """The other direction. A key checked but never declared means every future
    `.dmg` inspection reports it absent, and the signal is trained away."""
    inspected = _usage_description_keys(_inspector_plist_keys())
    stale = sorted(inspected - set(_spec_info_plist()))
    assert not stale, (
        f"scripts/inspect-dmg.py looks for {stale}, which the spec does not declare"
    )


# ---- the two services the hotkey actually needs --------------------------


def test_both_permissions_the_dictation_key_needs_are_declared() -> None:
    """The #182 pair, named explicitly.

    Since macOS 10.15 a keyboard event tap needs **Input Monitoring** as well as
    Accessibility, and the microphone is a third service the same key reaches.
    Losing either string reintroduces a refusal with no prompt attached.
    """
    declared = _spec_info_plist()
    for key in ("NSMicrophoneUsageDescription", "NSInputMonitoringUsageDescription"):
        assert key in declared, f"{key} is missing from the macOS bundle"


def test_each_usage_description_says_what_it_is_for() -> None:
    """macOS shows this text verbatim in the permission dialog. An empty or
    placeholder string is what the user is asked to trust."""
    for key, value in _spec_info_plist().items():
        if not re.fullmatch(r"NS\w+UsageDescription", key):
            continue
        text = "".join(
            n.value for n in ast.walk(value)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        )
        assert len(text) > 30, f"{key} is too short to explain anything: {text!r}"
        assert "YazSes" in text, f"{key} does not name the app: {text!r}"


# ---- and the release job actually checks -------------------------------


def test_the_macos_build_workflow_verifies_the_bundle_it_ships() -> None:
    """Declaring the keys is half of it; the other half is a job that looks.

    `scripts/inspect-dmg.py` existed for a long time and was wired into nothing,
    so every `.dmg` shipped unexamined -- which is how a bundle reporting
    `CFBundleVersion` 0.1.2 survived from v0.1.3 to v2.18.0.
    """
    workflow = (REPO / ".github" / "workflows" / "build-macos.yml").read_text(
        encoding="utf-8"
    )
    assert "scripts/inspect-dmg.py" in workflow, (
        "the macOS build never inspects the .dmg it produces"
    )
    assert "--require-keys-from-spec" in workflow, (
        "the permission strings are not gated, so a bundle missing one would ship"
    )
