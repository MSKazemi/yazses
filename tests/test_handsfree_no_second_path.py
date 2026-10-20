"""Hands-free adds no code path a per-feature config does not already reach -- Phase 6 exit gate.

"No second daemon path may exist: a test asserts the preset adds no code path that a per-feature
config does not already reach." Three independent angles, so a regression has to defeat all of
them to go unnoticed:

* **Nothing reads the section at run time.** Only the config loader's preset step consults
  `[handsfree]`; no daemon, runtime, backend or CLI path branches on it.
* **The expander is pure.** Its import list is stdlib plus the config schema -- it cannot start
  anything, because it cannot import anything that does.
* **Same inputs, same objects.** The daemon's own builders, given the preset-resolved config and
  the hand-written one, make the same things.

No camera, no pointer, no socket.
"""
from __future__ import annotations

import ast
import dataclasses
import sys
import textwrap
from pathlib import Path

import pytest

import yazses
from yazses.config import load_config_checked
from yazses.platform import get_platform

SRC = Path(yazses.__file__).resolve().parent

#: What the pure modules may import. `yazses.config` is the schema (dataclasses); `configcheck`
#: is the validator the loader itself uses; `activation.confirm` is the pure consequence policy.
PURE_ALLOWED = {
    "yazses.config", "yazses.configcheck", "yazses.activation.confirm", "yazses.handsfree.stopword",
}


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
    return out


@pytest.mark.parametrize("module", ["preset.py", "recovery.py"])
def test_the_pure_modules_import_nothing_that_could_start_something(module):
    stdlib = set(sys.stdlib_module_names)
    foreign = {
        name for name in _imports(SRC / "handsfree" / module)
        if name.split(".")[0] not in stdlib and name not in PURE_ALLOWED
    }
    assert foreign == set(), f"{module} reaches beyond the pure layer: {sorted(foreign)}"


def test_the_expander_never_touches_the_daemon_runtime_or_a_backend():
    names = _imports(SRC / "handsfree" / "preset.py")
    forbidden = ("daemon", "runtime", "backend", "perception", "platform", "ipc", "headpointer",
                 "gesture", "facegesture", "gaze", "pointer", "cli", "subprocess", "socket", "threading")
    hits = {n for n in names if any(part in n.split(".") for part in forbidden)}
    assert hits == set()


def test_nothing_at_run_time_reads_the_handsfree_section():
    """Only `config.py` (which declares it and runs the preset step) may name it as an attribute."""
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        if path == SRC / "config.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "handsfree":
                offenders.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno} .handsfree")
            if (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant) and node.args[1].value == "handsfree"
            ):
                offenders.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno} getattr(.., 'handsfree')")
    assert offenders == []


def test_the_loader_is_the_only_caller_of_the_expander():
    callers = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if "resolve_raw" in path.read_text(encoding="utf-8") and path.name != "preset.py"
    ]
    assert callers == ["config.py"]


# --------------------------------------------------------------------------- same objects


PRESET = "[handsfree]\nenabled = true\n"
BY_HAND = textwrap.dedent(
    """
    [handsfree_safety]
    enabled = true
    stop_phrase = "pause hands free"
    [cmdsafety]
    enabled = true
    [perception]
    enabled = true
    [gaze]
    enabled = true
    route_dictation = true
    deixis = true
    confirm_destructive = true
    refuse_destructive_fallback = true
    [headpointer]
    enabled = true
    dwell_enabled = true
    [facegesture]
    enabled = true
    use_baseline = true
    confidence_floor = 0.5
    [gesture]
    enabled = true
    [gesture.chords]
    "brow_raise+nod" = "recenter"
    "brow_raise+shake" = "pause_pointer"
    """
)


class _Source:
    """A shared camera that refuses to be opened: building must not need one."""

    def consumer(self, name):
        class Lease:
            def start(self):
                raise AssertionError("building must not lease the camera")

            def stop(self):
                pass

            def latest(self):
                return None

        return Lease()

    def status(self):
        class S:
            failure_reason = None

        return S()


def _built(tmp_path, text: str, name: str):
    from yazses.core.daemon import Daemon

    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    cfg = load_config_checked(path).config
    daemon = Daemon(config=cfg, platform=get_platform())
    daemon._perception = _Source()
    daemon._handsfree_safety = daemon._build_handsfree_safety(cfg)
    daemon._headpointer = daemon._build_headpointer(cfg)
    daemon._gesture = daemon._build_gesture(cfg)
    gate = daemon._handsfree_safety
    sources = daemon._build_face_gesture_source(cfg)
    return {
        "gate": None if gate is None else (type(gate).__name__, gate.status().state.value,
                                           [s.name for s in gate.status().sources],
                                           dataclasses.asdict(gate._limits)),
        "headpointer": (type(daemon._headpointer).__name__, daemon._headpointer.active,
                        daemon._headpointer.reason),
        "gesture": (type(daemon._gesture).__name__, daemon._gesture.active, daemon._gesture.reason,
                    sorted(daemon._gesture.runner.engine.bindings.items())
                    if daemon._gesture.runner else None),
        "face": [type(s).__name__ for s in sources],
        "gaze_sections": dataclasses.asdict(cfg.gaze),
    }


def test_the_daemon_builds_the_same_objects_from_the_preset_as_from_the_hand_written_config(tmp_path):
    from_preset = _built(tmp_path, PRESET, "p.toml")
    by_hand = _built(tmp_path, BY_HAND, "h.toml")
    assert from_preset == by_hand


def test_that_comparison_is_not_vacuous(tmp_path):
    built = _built(tmp_path, PRESET, "p.toml")
    nothing = _built(tmp_path, "", "empty.toml")
    assert built != nothing
    assert built["gate"] is not None and nothing["gate"] is None
    assert built["face"] == ["FaceGestureBackend"] and nothing["face"] == []
    assert built["gesture"][3], "the chords must actually be bound in the built runtime"
