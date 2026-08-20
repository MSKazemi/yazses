"""A branch on `Platform.name` must name a platform that exists.

`yazses doctor` has one row per thing that can go wrong, and two of those rows
are gated on which OS is running. The gate is a string comparison against
`Platform.name` -- and the elevation row compared against `"windows"`, a value
no backend has ever produced. `Platform.name` is a `sys.platform` string, so the
Windows bundle declares `"win32"`; the comparison was therefore false on Windows
and the "Elevated windows" row could not appear on the only OS it exists for.

Nothing caught it. The unit test fed `_elevation_check("windows")` -- the same
invented string -- and passed, and `docs/capability-matrix.md` went on telling
the reader that `yazses doctor` reports which elevation case they are in.

So the fix is not a corrected literal. The names now live in one place
(`platform/base.py`) and every bundle sets `name=` from them, and these tests
read the code rather than restating it: any future comparison against a string
no `build_platform()` declares fails here, whatever the file or the row.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from yazses.platform import base as base_mod
from yazses.platform.base import (
    LINUX_PLATFORM_NAME,
    MACOS_PLATFORM_NAME,
    WINDOWS_PLATFORM_NAME,
)
from yazses.platform.bsd import BSD_PREFIXES
from yazses.system.doctor import _elevation_check, _keyboard_capture_check

SRC = Path(__file__).resolve().parents[1] / "src" / "yazses"
DOCTOR = SRC / "system" / "doctor.py"
BUNDLES = {
    "linux": SRC / "platform" / "linux" / "__init__.py",
    "macos": SRC / "platform" / "macos" / "__init__.py",
    "windows": SRC / "platform" / "windows" / "__init__.py",
    "bsd": SRC / "platform" / "bsd" / "__init__.py",
}


# ---- reading the declared names out of the code -------------------------


def _declared_name(path: Path) -> ast.expr:
    """The `name=` argument of the `Platform(...)` call in a bundle."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "Platform"):
            continue
        for kw in node.keywords:
            if kw.arg == "name":
                return kw.value
    raise AssertionError(f"no Platform(name=...) in {path}")


def _resolve(expr: ast.expr) -> str | None:
    """The literal a `name=` argument evaluates to, or None when it is dynamic."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Name):
        value = getattr(base_mod, expr.id, None)
        return value if isinstance(value, str) else None
    return None  # e.g. BSD's `sys.platform` -- known only at runtime


def _static_declared_names() -> set[str]:
    names = set()
    for path in BUNDLES.values():
        resolved = _resolve(_declared_name(path))
        if resolved is not None:
            names.add(resolved)
    return names


# ---- reading the comparisons out of doctor ------------------------------


def _is_platform_name_expr(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return "platform_name" in node.id
    if isinstance(node, ast.Attribute):
        return node.attr == "name" and isinstance(node.value, ast.Name) and node.value.id == "platform"
    return False


def _compared_operands(path: Path) -> list[tuple[int, str, bool]]:
    """Every `<platform name> == X` in a module, as (line, resolved, was_literal).

    `was_literal` is the interesting half. A comparison written as a bare string
    can drift away from the bundle that declares the name without anything
    noticing -- that is the whole defect -- so the rule is that these branches
    compare against the shared constant, and the resolved value must still be a
    name some `build_platform()` actually produces.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.comparators) != 1:
            continue
        right = node.comparators[0]
        if not _is_platform_name_expr(node.left) and not _is_platform_name_expr(right):
            continue
        other = right if _is_platform_name_expr(node.left) else node.left
        candidates: list[ast.expr] = []
        if isinstance(other, (ast.Tuple, ast.List, ast.Set)):
            candidates.extend(other.elts)
        else:
            candidates.append(other)
        for candidate in candidates:
            if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
                found.append((node.lineno, candidate.value, True))
            elif isinstance(candidate, ast.Name):
                resolved = _resolve(candidate)
                if resolved is not None:
                    found.append((node.lineno, resolved, False))
    return found


# ---- the guards ---------------------------------------------------------


def test_every_bundle_declares_its_name_from_the_shared_constants():
    """A literal in a bundle can drift from a literal in a reader. A name cannot."""
    for label, path in BUNDLES.items():
        expr = _declared_name(path)
        if label == "bsd":
            # BSD deliberately reports the real sys.platform ("freebsd14"), so it
            # has no constant to share -- but it must not be a hardcoded string
            # either, which would name the wrong BSD.
            assert not isinstance(expr, ast.Constant), "BSD must report sys.platform"
            continue
        assert isinstance(expr, ast.Name), (
            f"{path.name} hardcodes Platform(name=...); use the constant in "
            "platform/base.py so a reader cannot compare against a different string"
        )
        assert _resolve(expr) is not None, f"{path.name}: unknown name constant {expr.id}"


def test_the_declared_names_are_the_values_the_factory_dispatches_on():
    """`get_platform()` picks a bundle by `sys.platform`; the bundle then reports a
    name. If those two disagree, every downstream comparison is against a string
    the running process cannot have."""
    factory = (SRC / "platform" / "factory.py").read_text(encoding="utf-8")
    tree = ast.parse(factory)
    dispatched = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.comparators) != 1:
            continue
        left = node.left
        if not (
            isinstance(left, ast.Attribute)
            and left.attr == "platform"
            and isinstance(left.value, ast.Name)
            and left.value.id == "sys"
        ):
            continue
        target = node.comparators[0]
        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            dispatched.add(target.value)
    assert dispatched, "no sys.platform dispatch found in factory.py"
    assert dispatched == {
        LINUX_PLATFORM_NAME,
        MACOS_PLATFORM_NAME,
        WINDOWS_PLATFORM_NAME,
    }


@pytest.mark.parametrize("lineno,resolved,was_literal", _compared_operands(DOCTOR))
def test_doctor_only_compares_against_names_a_backend_declares(lineno, resolved, was_literal):
    """The #182-shaped defect: a row silently switched off by a string typo."""
    allowed = _static_declared_names()
    assert resolved in allowed or resolved.startswith(BSD_PREFIXES), (
        f"doctor.py:{lineno} compares the platform name against {resolved!r}, which "
        f"no build_platform() declares (declared: {sorted(allowed)}). That branch "
        "can never run."
    )
    assert not was_literal, (
        f"doctor.py:{lineno} compares the platform name against the literal "
        f"{resolved!r}. Import the constant from platform/base.py instead -- a "
        "literal here is free to drift away from the bundle that sets the name, "
        "which is how the Windows elevation row went missing."
    )


def test_doctor_actually_compares_something():
    """The guard above passes vacuously on an empty list -- prove it has rows."""
    operands = _compared_operands(DOCTOR)
    assert len(operands) >= 2, operands


# ---- the row that was missing -------------------------------------------


def test_the_elevation_row_appears_under_the_name_windows_declares():
    check = _elevation_check(WINDOWS_PLATFORM_NAME)
    assert check is not None, "the Windows-only doctor row is unreachable on Windows"
    assert check[0] == "Elevated windows"


def test_the_elevation_row_is_absent_on_every_other_platform():
    for name in (LINUX_PLATFORM_NAME, MACOS_PLATFORM_NAME, "freebsd14", "windows"):
        assert _elevation_check(name) is None, name


def test_the_capability_matrix_promise_and_the_row_move_together():
    """`docs/capability-matrix.md` tells the reader doctor reports their elevation
    case. It said so throughout the period the row could not render."""
    doc = (Path(__file__).resolve().parents[1] / "docs" / "capability-matrix.md").read_text(
        encoding="utf-8"
    )
    promises = "yazses doctor` reports which case you are in" in doc
    assert promises, "the documented promise moved; re-point this guard at it"
    assert _elevation_check(WINDOWS_PLATFORM_NAME) is not None


# ---- the other gated row ------------------------------------------------


def test_the_linux_input_group_advice_is_keyed_to_the_declared_linux_name():
    """The keyboard row's Linux branch is gated the same way; it happened to be
    correct, and nothing was holding it that way."""

    class _Denied:
        def check_keyboard_capture(self):
            from yazses.platform.base import PermissionState

            return PermissionState.DENIED

        def how_to_grant(self):
            return "GENERIC-FALLBACK"

    _name, status, detail = _keyboard_capture_check(_Denied(), LINUX_PLATFORM_NAME)
    assert status == "FAIL"
    assert "usermod -aG input" in detail
    assert "GENERIC-FALLBACK" not in detail
