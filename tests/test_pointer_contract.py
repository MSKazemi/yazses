"""The PointerSink contract, applied to the fake — plus the rules the layer itself obeys.

Three things are checked here.

**The shared suite runs against three fakes, not one.** ``tests/pointer_contract.py`` is
the suite every platform backend will inherit, and half of its assertions are about what
a *partial* backend does: absolute motion that is not there must raise, a middle button
that does not exist must raise, a missing horizontal axis must raise. Run only against a
fake that can do everything, every one of those branches would be dead code that passes
because it never executes — the shape of guard this repository has shipped inert before.
So the suite is applied to a full fake, a relative-only/vertical-only one and a
two-button one, and both sides of each branch really run.

**The fake's own extras.** Failure injection, ``clear()``, the recorded click being two
actions, and the capability helpers in :mod:`yazses.pointer.base` are tested directly.

**The layer stays a boundary.** An AST scan asserts that ``src/yazses/pointer/`` imports
nothing but the standard library and itself — no camera, no MediaPipe, no
``yazses.headpointer``, no ``yazses.gaze`` — and runs no subprocess. The whole reason
ADR-v2-146 exists is that Head-Pointer must not contain platform commands; a protocol
module that grew a ``subprocess.run`` would have quietly become the thing it replaced.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

import yazses
from tests.pointer_contract import PointerSinkContract
from tests.pointer_fake import (
    FULL_CAPABILITIES,
    FakePointerSink,
    PointerAction,
    PointerActionKind,
)
from yazses.pointer.base import (
    PointerBackendError,
    PointerButton,
    PointerCapabilities,
    PointerError,
    PointerSink,
    PointerUnsupportedError,
    check_finite,
    require_absolute,
    require_button,
    require_relative,
    require_scroll,
)

POINTER_DIR = Path(yazses.__file__).resolve().parent / "pointer"


# --------------------------------------------------------------------------- #
# The shared suite, against three differently-capable fakes.
# --------------------------------------------------------------------------- #
class _FakeContract(PointerSinkContract):
    """Wire the four contract hooks to :class:`FakePointerSink`."""

    capabilities = FULL_CAPABILITIES

    def make_sink(self) -> FakePointerSink:
        return FakePointerSink(self.capabilities)

    def recorded(self, sink: PointerSink) -> list[PointerAction]:
        assert isinstance(sink, FakePointerSink)
        return sink.actions

    def induce_failure(self, sink: PointerSink) -> None:
        assert isinstance(sink, FakePointerSink)
        sink.fail_with()

    def clear_failure(self, sink: PointerSink) -> None:
        assert isinstance(sink, FakePointerSink)
        sink.clear_failure()


class TestFullFakeSink(_FakeContract):
    """Everything supported — the positive branch of every capability test."""


class TestRelativeOnlyFakeSink(_FakeContract):
    """No absolute motion, no horizontal scroll: the honest-refusal branch."""

    capabilities = PointerCapabilities(
        backend="fake-relative-only",
        relative_motion=True,
        absolute_motion=False,
        buttons=frozenset(PointerButton),
        scroll_vertical=True,
        scroll_horizontal=False,
    )


class TestTwoButtonFakeSink(_FakeContract):
    """Left and right only, and no scroll axis at all."""

    capabilities = PointerCapabilities(
        backend="fake-two-button",
        relative_motion=True,
        absolute_motion=True,
        buttons=frozenset({PointerButton.LEFT, PointerButton.RIGHT}),
        scroll_vertical=False,
        scroll_horizontal=False,
    )


# --------------------------------------------------------------------------- #
# The fake's own behaviour.
# --------------------------------------------------------------------------- #
def test_click_is_recorded_as_a_press_and_a_release() -> None:
    sink = FakePointerSink()
    sink.click(PointerButton.RIGHT)
    kinds = [a.kind for a in sink.actions]
    assert kinds == [PointerActionKind.BUTTON_PRESS, PointerActionKind.BUTTON_RELEASE]
    assert {a.button for a in sink.actions} == {PointerButton.RIGHT}


def test_actions_is_a_copy_so_a_caller_cannot_rewrite_history() -> None:
    sink = FakePointerSink()
    sink.move_relative(1.0, 2.0)
    sink.actions.clear()
    assert sink.actions == [PointerAction.move_relative(1.0, 2.0)]


def test_clear_forgets_actions_but_not_state() -> None:
    sink = FakePointerSink()
    sink.move_relative(1.0, 2.0)
    sink.clear()
    assert sink.actions == []
    sink.move_relative(3.0, 4.0)
    assert sink.actions == [PointerAction.move_relative(3.0, 4.0)]


def test_close_is_recorded_once() -> None:
    sink = FakePointerSink()
    sink.close()
    sink.close()
    assert sink.actions == [PointerAction.close()]
    assert sink.closed is True


def test_a_specific_failure_is_the_one_raised() -> None:
    sink = FakePointerSink()
    boom = PointerBackendError("compositor refused the session")
    sink.fail_with(boom)
    with pytest.raises(PointerBackendError) as excinfo:
        sink.scroll(0.0, 1.0)
    assert excinfo.value is boom


def test_failure_persists_until_it_is_cleared() -> None:
    """A display server does not come back for the next call either."""
    sink = FakePointerSink()
    sink.fail_with()
    for _ in range(3):
        with pytest.raises(PointerBackendError):
            sink.move_relative(1.0, 1.0)
    assert sink.actions == []
    sink.clear_failure()
    sink.move_relative(1.0, 1.0)
    assert sink.actions == [PointerAction.move_relative(1.0, 1.0)]


def test_close_works_even_while_the_backend_is_failing() -> None:
    """Cleanup after an error must not raise a second error on top of the first."""
    sink = FakePointerSink()
    sink.fail_with()
    sink.close()
    assert sink.closed is True


def test_a_zero_delta_is_still_a_recorded_action() -> None:
    """A no-op move is the caller's decision, not something the sink swallows."""
    sink = FakePointerSink()
    sink.move_relative(0.0, 0.0)
    assert sink.actions == [PointerAction.move_relative(0.0, 0.0)]


# --------------------------------------------------------------------------- #
# Capabilities and the shared guard helpers.
# --------------------------------------------------------------------------- #
def test_capabilities_default_to_nothing_supported() -> None:
    """A backend must opt in to each capability; forgetting one under-promises."""
    caps = PointerCapabilities(backend="bare")
    assert not caps.relative_motion
    assert not caps.absolute_motion
    assert caps.buttons == frozenset()
    assert not caps.scroll_vertical and not caps.scroll_horizontal


def test_capabilities_are_hashable_values() -> None:
    assert FULL_CAPABILITIES == PointerCapabilities(
        backend="fake",
        relative_motion=True,
        absolute_motion=True,
        buttons=frozenset(PointerButton),
        scroll_vertical=True,
        scroll_horizontal=True,
    )
    assert len({FULL_CAPABILITIES, FULL_CAPABILITIES}) == 1


def test_supports_scroll_ignores_an_axis_that_is_not_used() -> None:
    caps = PointerCapabilities(backend="v-only", scroll_vertical=True)
    assert caps.supports_scroll(0.0, -3.0)
    assert not caps.supports_scroll(1.0, 0.0)
    assert not caps.supports_scroll(1.0, -3.0)


def test_require_helpers_name_the_backend_in_the_message() -> None:
    caps = PointerCapabilities(backend="x11-ish", relative_motion=True)
    require_relative(caps)
    for call in (
        lambda: require_absolute(caps),
        lambda: require_button(caps, PointerButton.LEFT),
        lambda: require_scroll(caps, 0.0, 1.0),
    ):
        with pytest.raises(PointerUnsupportedError, match="x11-ish"):
            call()
    with pytest.raises(PointerUnsupportedError, match="x11-ish"):
        require_relative(PointerCapabilities(backend="x11-ish"))


def test_check_finite_names_the_offending_argument() -> None:
    check_finite(dx=1.0, dy=-2.5)
    with pytest.raises(ValueError, match="dy"):
        check_finite(dx=1.0, dy=float("nan"))


def test_unsupported_and_backend_errors_share_one_base() -> None:
    """Callers that only need 'did it work' catch PointerError and get both."""
    assert issubclass(PointerUnsupportedError, PointerError)
    assert issubclass(PointerBackendError, PointerError)
    assert issubclass(PointerError, RuntimeError)
    assert not issubclass(PointerUnsupportedError, PointerBackendError), (
        "permanently unsupported and transiently failed are different answers"
    )


# --------------------------------------------------------------------------- #
# The protocol shape.
# --------------------------------------------------------------------------- #
def test_the_protocol_has_exactly_the_six_contract_methods() -> None:
    """`PointerSink` is runtime_checkable: a seventh method silently un-matches
    every backend written against the old shape. Grow it only with the backends."""
    defined = {n for n in vars(PointerSink) if not n.startswith("_")}
    assert defined == {
        "capabilities",
        "move_relative",
        "move_absolute",
        "click",
        "scroll",
        "close",
    }


def test_an_object_missing_a_method_is_not_a_pointer_sink() -> None:
    class HalfASink:
        def capabilities(self) -> None: ...
        def move_relative(self, dx: float, dy: float) -> None: ...

    assert not isinstance(HalfASink(), PointerSink)


# --------------------------------------------------------------------------- #
# The layer stays a boundary.
# --------------------------------------------------------------------------- #
def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _pointer_sources() -> list[Path]:
    files = sorted(p for p in POINTER_DIR.rglob("*.py") if "__pycache__" not in p.parts)
    assert files, f"no pointer sources found under {POINTER_DIR} — the scan would pass blind"
    return files


@pytest.mark.parametrize("path", _pointer_sources(), ids=lambda p: p.name)
def test_the_pointer_layer_imports_only_stdlib_and_itself(path: Path) -> None:
    for module in _imported_modules(path):
        top = module.split(".")[0]
        if top == "yazses":
            assert module.startswith("yazses.pointer"), (
                f"{path.name} imports {module} — the pointer boundary must not depend on "
                "another yazses package (no camera, gaze, head-pose or gesture concepts)"
            )
            continue
        assert top in sys.stdlib_module_names, (
            f"{path.name} imports third-party module {module!r}; the pointer protocol "
            "layer is pure and dependency-free (platform backends may not be, but they "
            "import lazily inside the function that needs them)"
        )


@pytest.mark.parametrize("path", _pointer_sources(), ids=lambda p: p.name)
def test_the_pointer_layer_runs_no_commands(path: Path) -> None:
    """No `xdotool` here. Command construction belongs to a platform backend."""
    offending = sorted(
        m for m in _imported_modules(path) if m.split(".")[0] in {"subprocess", "pty", "ctypes"}
    )
    assert not offending, f"{path.name} imports {offending}"
    source = path.read_text(encoding="utf-8")
    for call in ("subprocess.", "os.system(", "os.popen(", "shutil.which(", "os.exec"):
        assert call not in source, f"{path.name} reaches for {call!r}"
