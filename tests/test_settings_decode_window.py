"""The four new decode/injection settings, driven through the real Qt window.

The controller tests next door prove the *rules*. This proves the widgets are
connected to them, which is a separate failure and the one that survives a green
unit suite: a box that renders, accepts a change, and writes nothing on Apply looks
identical to one that works.

It matters more here than for the first three settings because the Apply loop had to
stop assuming every row is a combo box. A `QLineEdit` has no `currentText()` and a
`QSpinBox` has no `currentData()`, so each row now carries its own reader — and a
reader wired to the wrong widget type raises inside a Qt slot, where the traceback
goes nowhere the user can see.

Offscreen, like the sibling window test, so it runs in CI without a display.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.controls import compute_type_choices  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class _Recorder:
    def __init__(self, cfg=None):
        self.writes: list[tuple] = []
        self._cfg = cfg if cfg is not None else Config()

    def load(self):
        return self._cfg

    def write(self, section, key, value, quote):
        self.writes.append((section, key, value, quote))

    def probe(self, modules):
        return []

    def written(self, section, key):
        """The value written for one key, or None."""
        for s, k, value, _quote in self.writes:
            if (s, k) == (section, key):
                return value
        return None


def _window(qapp, rec):
    win = SettingsWindow(build_settings_model(rec._cfg), SettingsController(
        rec.load, rec.write, rec.probe
    ))
    # Same reasoning as the sibling test: a real modal would block forever, and
    # `_daemon_running` asks the *host*, so on a developer machine with a daemon up
    # Apply would reach the restart prompt and hang.
    win._confirm_experimental = lambda row: True  # type: ignore[method-assign]
    win._confirm_reset = lambda diff, labels: True  # type: ignore[method-assign]
    win._warn = lambda title, body: None  # type: ignore[method-assign]
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._daemon_status = lambda: None  # type: ignore[method-assign]
    win._confirm_restart = lambda: False  # type: ignore[method-assign]
    win._run_restart = lambda: (False, "not in a test")  # type: ignore[method-assign]
    return win


# ---- the widgets exist and open on the configured values -------------------


def test_every_new_row_is_built(qapp):
    win = _window(qapp, _Recorder())
    for attr in ("_compute_box", "_prompt_edit", "_guard_box", "_padding_spin"):
        assert getattr(win, attr, None) is not None, f"{attr} was never built"


def test_the_widgets_open_on_the_configured_values_not_the_defaults(qapp):
    """A widget built from a default writes that default on the next Apply.

    That is how a settings window quietly resets a value the user never touched —
    they change the hotkey, click Apply, and their padding goes back to 300.
    """
    cfg = Config()
    cfg.stt.initial_prompt = "Kubernetes, Seyedkazemi"
    cfg.injection.target_guard = "warn"
    cfg.accessibility.pre_speech_padding_ms = 750
    win = _window(qapp, _Recorder(cfg))

    assert win._prompt_edit.text() == "Kubernetes, Seyedkazemi"
    assert win._guard_box.currentData() == "warn"
    assert win._padding_spin.value() == 750


def test_the_compute_box_offers_what_this_machine_supports(qapp):
    win = _window(qapp, _Recorder())
    shown = [win._compute_box.itemText(i) for i in range(win._compute_box.count())]
    assert shown == compute_type_choices("cpu", current=Config().stt.compute_type)


def test_the_spin_box_cannot_produce_an_out_of_range_value(qapp):
    """Why the controller clamps rather than refuses: the widget already bounds it."""
    from yazses.settingsui.controls import PADDING_MAX_MS, PADDING_MIN_MS

    win = _window(qapp, _Recorder())
    win._padding_spin.setValue(99999)
    assert win._padding_spin.value() == PADDING_MAX_MS
    win._padding_spin.setValue(-5)
    assert win._padding_spin.value() == PADDING_MIN_MS


# ---- Apply actually carries each widget type through -----------------------


def test_applying_a_line_edit_writes_it(qapp):
    """A QLineEdit has no `currentText()`; the row's reader must be `.text()`."""
    rec = _Recorder()
    win = _window(qapp, rec)
    win._prompt_edit.setText("YazSes, ctranslate2")
    changed, errors = win._apply_speech()
    assert changed and not errors
    assert rec.written("stt", "initial_prompt") == "YazSes, ctranslate2"


def test_applying_a_spin_box_writes_an_int(qapp):
    """A QSpinBox has no `currentData()`; the row's reader must be `.value()`."""
    rec = _Recorder()
    win = _window(qapp, rec)
    win._padding_spin.setValue(500)
    changed, errors = win._apply_speech()
    assert changed and not errors
    assert rec.written("accessibility", "pre_speech_padding_ms") == 500


def test_applying_a_data_backed_combo_writes_the_value_not_the_label(qapp):
    """The guard box shows "Type it anyway, but warn me" and must write "warn"."""
    rec = _Recorder()
    win = _window(qapp, rec)
    index = win._guard_box.findData("off")
    assert index >= 0
    win._guard_box.setCurrentIndex(index)
    changed, errors = win._apply_speech()
    assert changed and not errors
    assert rec.written("injection", "target_guard") == "off"


def test_applying_the_compute_box_writes_it(qapp):
    rec = _Recorder()
    win = _window(qapp, rec)
    supported = compute_type_choices("cpu")
    other = next((n for n in supported if n != Config().stt.compute_type), None)
    if other is None:  # pragma: no cover - a build offering exactly one type
        pytest.skip("this machine supports only one compute type")
    win._compute_box.setCurrentIndex(supported.index(other))
    changed, errors = win._apply_speech()
    assert changed and not errors
    assert rec.written("stt", "compute_type") == other


def test_untouched_rows_write_nothing(qapp):
    """Apply must not rewrite every setting it can see.

    Rewriting an unchanged value is not harmless: it would drop a hand-written
    comment's neighbour formatting and, for a value this window shows but cannot
    validate, re-assert a config the daemon may already have rejected.
    """
    rec = _Recorder()
    win = _window(qapp, rec)
    changed, errors = win._apply_speech()
    assert not changed and not errors
    assert rec.writes == []


def test_all_four_apply_in_one_click(qapp):
    rec = _Recorder()
    win = _window(qapp, rec)
    win._prompt_edit.setText("one two")
    win._padding_spin.setValue(120)
    win._guard_box.setCurrentIndex(win._guard_box.findData("warn"))

    changed, errors = win._apply_speech()

    assert changed and not errors
    assert rec.written("stt", "initial_prompt") == "one two"
    assert rec.written("accessibility", "pre_speech_padding_ms") == 120
    assert rec.written("injection", "target_guard") == "warn"


def test_a_refused_value_reports_and_leaves_the_others_saved(qapp):
    """One bad row must not cost the user the rest of their edits.

    The refused value stays on screen next to the error that explains it, so the fix
    is one more change rather than re-doing the whole form.
    """
    rec = _Recorder()
    win = _window(qapp, rec)
    # A compute type this machine cannot run, forced past the widget the way a
    # hand-edited config would present one.
    win._compute_box.addItem("float64")
    win._compute_box.setCurrentIndex(win._compute_box.count() - 1)
    win._prompt_edit.setText("still saved")

    changed, errors = win._apply_speech()

    assert changed, "the good row must still have been written"
    assert errors and "float64" in errors[0]
    assert rec.written("stt", "initial_prompt") == "still saved"
    assert rec.written("stt", "compute_type") is None
    assert win._compute_box.currentText() == "float64", "intent stays on screen"
