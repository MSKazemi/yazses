from __future__ import annotations

import os
import tomllib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.config import load_config  # noqa: E402
from yazses.language.service import (  # noqa: E402
    apply_language_change,
    prepare_language_change,
)
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402
from yazses.system.configedit import set_config_key  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _english(path) -> None:
    path.write_text(
        '[stt]\n'
        'engine = "faster-whisper"\n'
        'model = "base.en"\n'
        'language = "en"\n'
        'chinese_script = ""\n',
        encoding="utf-8",
    )


def _controller(path, *, dep_ready=True, model_cached=True):
    dep = {"ready": dep_ready}
    cache = {"ready": model_cached}

    def missing(_mods):
        return [] if dep["ready"] else ["opencc"]

    def cached(_model):
        return cache["ready"]

    def preview(profile, *, model=None):
        return prepare_language_change(
            path,
            profile,
            model=model,
            missing_modules_fn=missing,
            blocked_probe=lambda _packages: None,
            cache_probe=cached,
        )

    def apply(profile, *, model=None, echo=lambda _line: None):
        def install(_packages, echo=None):
            dep["ready"] = True
            return True

        def download(_model, echo=None):
            cache["ready"] = True
            return path.parent / "model"

        return apply_language_change(
            path,
            profile,
            model=model,
            missing_modules_fn=missing,
            blocked_probe=lambda _packages: None,
            cache_probe=cached,
            installer=install,
            downloader=download,
            echo=echo,
        )

    return SettingsController(
        load_config=lambda: load_config(path),
        writer=lambda s, k, v, q: set_config_key(path, s, k, v, quote=q),
        language_previewer=preview,
        language_applier=apply,
    )


def _window(qapp, monkeypatch, path, *, dep_ready=True, model_cached=True):
    monkeypatch.setattr(
        SettingsWindow,
        "_probe_devices",
        lambda self: ([], None),
    )
    controller = _controller(
        path,
        dep_ready=dep_ready,
        model_cached=model_cached,
    )
    win = SettingsWindow(build_settings_model(load_config(path)), controller)
    win._warn = lambda _title, _body: None  # type: ignore[method-assign]
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._daemon_status = lambda: None  # type: ignore[method-assign]
    win._confirm_restart = lambda: False  # type: ignore[method-assign]
    return win


def test_settings_model_derives_profile_without_storing_a_second_flag(tmp_path):
    path = tmp_path / "config.toml"
    _english(path)

    model = build_settings_model(load_config(path))

    assert model.language_profile == "en"
    assert "language_profile" not in path.read_text(encoding="utf-8")


def test_selecting_mandarin_previews_repaired_model_and_language_without_writing(
    qapp,
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "config.toml"
    _english(path)
    before = path.read_bytes()
    win = _window(
        qapp,
        monkeypatch,
        path,
        dep_ready=False,
        model_cached=False,
    )

    win._profile_box.setCurrentIndex(win._profile_box.findData("zh-CN"))

    assert path.read_bytes() == before
    assert win._model_box.currentText() == "small"
    assert win._language_box.currentData() == "zh"
    assert win._language_box.isEnabled() is False
    assert "chinese_script" in win._hint.text()
    assert "One-time preparation" in win._hint.text()
    assert "Nothing changes until Apply" in win._hint.text()


def test_profile_transaction_owns_model_and_language_writes(qapp, monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    _english(path)
    win = _window(qapp, monkeypatch, path)

    win._profile_box.setCurrentIndex(win._profile_box.findData("zh-TW"))
    changed, errors = win._apply_speech(skip_profile_owned=True)

    assert not changed
    assert errors == []
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["stt"]["model"] == "base.en"
    assert parsed["stt"]["language"] == "en"
    assert parsed["stt"]["chinese_script"] == ""


def test_settings_controller_uses_same_atomic_profile_service(tmp_path):
    path = tmp_path / "config.toml"
    _english(path)
    controller = _controller(
        path,
        dep_ready=False,
        model_cached=False,
    )

    result = controller.apply_language_profile("zh-CN")

    assert result.ok
    assert result.restart_required
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["stt"] == {
        "engine": "faster-whisper",
        "model": "small",
        "language": "zh",
        "chinese_script": "simplified",
    }


def test_apply_launches_one_language_worker_with_auto_model_not_explicit_override(
    qapp,
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "config.toml"
    _english(path)
    win = _window(
        qapp,
        monkeypatch,
        path,
        dep_ready=False,
        model_cached=False,
    )
    win._confirm_language_requirements = lambda _prepared: True  # type: ignore[method-assign]

    started = []
    win._start_language_worker = (  # type: ignore[method-assign]
        lambda profile, model: started.append((profile, model))
    )

    win._profile_box.setCurrentIndex(win._profile_box.findData("zh-CN"))
    started_ok, error = win._start_language_profile_apply()

    assert started_ok
    assert error is None
    assert started == [("zh-CN", None)]


def test_user_selected_compatible_model_is_passed_as_profile_override(
    qapp,
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "config.toml"
    _english(path)
    win = _window(qapp, monkeypatch, path)
    win._confirm_language_requirements = lambda _prepared: True  # type: ignore[method-assign]
    started = []
    win._start_language_worker = (  # type: ignore[method-assign]
        lambda profile, model: started.append((profile, model))
    )

    win._profile_box.setCurrentIndex(win._profile_box.findData("zh-CN"))
    win._model_box.setCurrentText("large-v3")
    started_ok, error = win._start_language_profile_apply()

    assert started_ok
    assert error is None
    assert started == [("zh-CN", "large-v3")]


def test_switching_to_custom_unlocks_low_level_language_picker(
    qapp,
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "config.toml"
    _english(path)
    win = _window(qapp, monkeypatch, path)

    assert win._language_box.isEnabled() is False
    win._profile_box.setCurrentIndex(win._profile_box.findData(""))

    assert win._language_box.isEnabled() is True
    assert not win._language_profile_transaction_pending()


def test_successful_worker_result_settles_profile_controls_and_restart(
    qapp,
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "config.toml"
    _english(path)
    controller = _controller(path)
    win = _window(qapp, monkeypatch, path)

    result = controller.apply_language_profile("zh-TW")
    assert result.ok

    offered = []
    win._restart_when_installed = "Saved."
    win._offer_restart = lambda summary="": offered.append(summary)  # type: ignore[method-assign]
    win._on_language_finished(result)

    assert win._profile_baseline == "zh-TW"
    assert win._profile_box.currentData() == "zh-TW"
    assert win._model_baseline == "small"
    assert win._language_baseline == "zh"
    assert win._language_box.isEnabled() is False
    assert len(offered) == 1
    assert "Language profile set to zh-TW" in offered[0]
