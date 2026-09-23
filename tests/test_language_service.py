from __future__ import annotations

import tomllib

from yazses.language.service import (
    apply_language_change,
    prepare_language_change,
)
from yazses.system import configedit


def _english(path) -> None:
    path.write_text(
        '[stt]\n'
        'engine = "faster-whisper"\n'
        'model = "base.en"\n'
        'language = "en"\n'
        'chinese_script = ""\n'
        '\n[hotkey]\n'
        'key = "right_alt"\n',
        encoding="utf-8",
    )


def test_prepare_is_read_only_and_reports_exact_requirements(tmp_path):
    path = tmp_path / "config.toml"
    _english(path)
    before = path.read_bytes()

    prepared = prepare_language_change(
        path,
        "zh-CN",
        missing_modules_fn=lambda _mods: ["opencc"],
        blocked_probe=lambda _packages: None,
        cache_probe=lambda _model: False,
    )

    assert path.read_bytes() == before
    assert prepared.plan.canonical_profile == "zh-CN"
    assert prepared.candidate_stt.model == "small"
    assert prepared.candidate_stt.language == "zh"
    assert prepared.candidate_stt.chinese_script == "simplified"
    assert prepared.requirements.missing_imports == ("opencc",)
    assert prepared.requirements.packages
    assert prepared.requirements.model == "small"
    assert not prepared.requirements.model_cached


def test_no_install_refuses_before_config_write(tmp_path):
    path = tmp_path / "config.toml"
    _english(path)
    before = path.read_bytes()

    result = apply_language_change(
        path,
        "zh-CN",
        allow_install=False,
        missing_modules_fn=lambda _mods: ["opencc"],
        blocked_probe=lambda _packages: None,
        cache_probe=lambda _model: True,
    )

    assert not result.ok
    assert result.category == "prerequisite"
    assert path.read_bytes() == before


def test_no_download_refuses_before_config_write(tmp_path):
    path = tmp_path / "config.toml"
    _english(path)
    before = path.read_bytes()

    result = apply_language_change(
        path,
        "zh-CN",
        allow_download=False,
        missing_modules_fn=lambda _mods: [],
        cache_probe=lambda _model: False,
    )

    assert not result.ok
    assert result.category == "prerequisite"
    assert path.read_bytes() == before


def test_dependency_failure_leaves_config_byte_exact(tmp_path):
    path = tmp_path / "config.toml"
    _english(path)
    before = path.read_bytes()

    result = apply_language_change(
        path,
        "zh-CN",
        missing_modules_fn=lambda _mods: ["opencc"],
        blocked_probe=lambda _packages: None,
        cache_probe=lambda _model: True,
        installer=lambda _packages, echo=None: False,
    )

    assert not result.ok
    assert result.category == "prerequisite"
    assert path.read_bytes() == before


def test_model_download_failure_leaves_config_byte_exact(tmp_path):
    path = tmp_path / "config.toml"
    _english(path)
    before = path.read_bytes()

    def fail_download(_model, echo=None):
        raise RuntimeError("network denied")

    result = apply_language_change(
        path,
        "zh-CN",
        missing_modules_fn=lambda _mods: [],
        cache_probe=lambda _model: False,
        downloader=fail_download,
    )

    assert not result.ok
    assert result.category == "prerequisite"
    assert path.read_bytes() == before


def test_success_prepares_prerequisites_then_commits_one_coherent_state(tmp_path):
    path = tmp_path / "config.toml"
    _english(path)
    dep_ready = False
    cached: set[str] = set()
    events: list[str] = []

    def missing(_mods):
        return [] if dep_ready else ["opencc"]

    def install(_packages, echo=None):
        nonlocal dep_ready
        events.append("install")
        dep_ready = True
        return True

    def cache(model):
        return model in cached

    def download(model, echo=None):
        events.append("download")
        cached.add(model)

    def commit(target, changes, **kwargs):
        events.append("commit")
        return configedit.set_config_keys_atomic(target, changes, **kwargs)

    result = apply_language_change(
        path,
        "zh-CN",
        missing_modules_fn=missing,
        blocked_probe=lambda _packages: None,
        cache_probe=cache,
        installer=install,
        downloader=download,
        commit_fn=commit,
        echo=lambda _line: None,
    )

    assert result.ok
    assert result.changed
    assert result.prerequisite_changed
    assert result.restart_required
    assert events == ["install", "download", "commit"]

    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["stt"] == {
        "engine": "faster-whisper",
        "model": "small",
        "language": "zh",
        "chinese_script": "simplified",
    }
    assert parsed["hotkey"]["key"] == "right_alt"


def test_installer_success_is_verified_before_commit(tmp_path):
    path = tmp_path / "config.toml"
    _english(path)
    before = path.read_bytes()

    result = apply_language_change(
        path,
        "zh-CN",
        missing_modules_fn=lambda _mods: ["opencc"],
        blocked_probe=lambda _packages: None,
        cache_probe=lambda _model: True,
        installer=lambda _packages, echo=None: True,
    )

    assert not result.ok
    assert "still unavailable" in result.error
    assert path.read_bytes() == before


def test_download_success_is_verified_before_commit(tmp_path):
    path = tmp_path / "config.toml"
    _english(path)
    before = path.read_bytes()

    result = apply_language_change(
        path,
        "zh-CN",
        missing_modules_fn=lambda _mods: [],
        cache_probe=lambda _model: False,
        downloader=lambda _model, echo=None: tmp_path / "model",
    )

    assert not result.ok
    assert "still not visible" in result.error
    assert path.read_bytes() == before


def test_concurrent_edit_is_re_resolved_and_unrelated_change_survives(tmp_path):
    path = tmp_path / "config.toml"
    _english(path)
    calls = 0

    def commit(target, changes, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            path.write_text(
                '[stt]\n'
                'engine = "faster-whisper"\n'
                'model = "small"\n'
                'language = "en"\n'
                'chinese_script = ""\n'
                '\n[hotkey]\n'
                'key = "left_ctrl"\n',
                encoding="utf-8",
            )
            raise configedit.ConfigEditConflictError("changed")
        return configedit.set_config_keys_atomic(target, changes, **kwargs)

    result = apply_language_change(
        path,
        "zh-CN",
        missing_modules_fn=lambda _mods: [],
        cache_probe=lambda _model: True,
        commit_fn=commit,
        echo=lambda _line: None,
    )

    assert result.ok
    assert calls == 2
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["stt"]["model"] == "small"
    assert parsed["stt"]["language"] == "zh"
    assert parsed["stt"]["chinese_script"] == "simplified"
    assert parsed["hotkey"]["key"] == "left_ctrl"


def test_before_side_effect_runs_before_install_download_or_commit(tmp_path):
    path = tmp_path / "config.toml"
    _english(path)
    events: list[str] = []
    dep_ready = False
    cached: set[str] = set()

    def missing(_mods):
        return [] if dep_ready else ["opencc"]

    def before(_prepared):
        events.append("guard")

    def install(_packages, echo=None):
        nonlocal dep_ready
        events.append("install")
        dep_ready = True
        return True

    def download(model, echo=None):
        events.append("download")
        cached.add(model)

    def commit(target, changes, **kwargs):
        events.append("commit")
        return configedit.set_config_keys_atomic(target, changes, **kwargs)

    result = apply_language_change(
        path,
        "zh-CN",
        missing_modules_fn=missing,
        blocked_probe=lambda _packages: None,
        cache_probe=lambda model: model in cached,
        installer=install,
        downloader=download,
        commit_fn=commit,
        before_side_effect=before,
        echo=lambda _line: None,
    )

    assert result.ok
    assert events == ["guard", "install", "download", "commit"]


def test_already_ready_profile_is_a_true_noop(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[stt]\n'
        'engine = "faster-whisper"\n'
        'model = "small"\n'
        'language = "zh"\n'
        'chinese_script = "traditional"\n',
        encoding="utf-8",
    )

    result = apply_language_change(
        path,
        "zh-TW",
        missing_modules_fn=lambda _mods: [],
        cache_probe=lambda _model: True,
    )

    assert result.ok
    assert not result.changed
    assert not result.prerequisite_changed
    assert not result.restart_required
