from __future__ import annotations

import os
import stat
import tomllib

import pytest

from yazses.system import configedit
from yazses.system.configedit import (
    ConfigChange,
    ConfigEditBusyError,
    ConfigEditConflictError,
    config_revision,
    set_config_key,
    set_config_keys_atomic,
)
from yazses.system.single_instance import SingleInstanceLock


def test_atomic_batch_creates_one_coherent_config(tmp_path):
    p = tmp_path / "config.toml"

    result = set_config_keys_atomic(
        p,
        [
            ConfigChange("stt", "model", "small"),
            ConfigChange("stt", "language", "zh"),
            ConfigChange("stt", "chinese_script", "simplified"),
        ],
    )

    parsed = tomllib.loads(p.read_text(encoding="utf-8"))
    assert parsed["stt"] == {
        "model": "small",
        "language": "zh",
        "chinese_script": "simplified",
    }
    assert len(result) == 3


def test_atomic_batch_preserves_comments_and_unrelated_sections(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '# keep this\n[stt]\nmodel = "base.en"\n\n[hotkey]\nkey = "right_alt"\n',
        encoding="utf-8",
    )

    set_config_keys_atomic(
        p,
        [
            ConfigChange("stt", "model", "small"),
            ConfigChange("stt", "language", "zh"),
            ConfigChange("stt", "chinese_script", "traditional"),
        ],
    )

    text = p.read_text(encoding="utf-8")
    assert "# keep this" in text
    assert '[hotkey]\nkey = "right_alt"' in text
    parsed = tomllib.loads(text)
    assert parsed["stt"]["model"] == "small"
    assert parsed["stt"]["language"] == "zh"
    assert parsed["stt"]["chinese_script"] == "traditional"


def test_invalid_candidate_never_replaces_the_original(tmp_path):
    p = tmp_path / "config.toml"
    original = b'[stt]\nmodel = "unterminated\n'
    p.write_bytes(original)

    with pytest.raises(tomllib.TOMLDecodeError):
        set_config_keys_atomic(
            p,
            [ConfigChange("stt", "language", "zh")],
        )

    assert p.read_bytes() == original


def test_exception_during_second_edit_rolls_back_byte_for_byte(tmp_path, monkeypatch):
    p = tmp_path / "config.toml"
    original = b'[stt]\nmodel = "base.en"\n'
    p.write_bytes(original)

    real = configedit._set_config_key_unlocked
    calls = 0

    def fail_on_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(configedit, "_set_config_key_unlocked", fail_on_second)

    with pytest.raises(RuntimeError, match="injected failure"):
        set_config_keys_atomic(
            p,
            [
                ConfigChange("stt", "model", "small"),
                ConfigChange("stt", "language", "zh"),
            ],
        )

    assert p.read_bytes() == original
    assert not list(tmp_path.glob(".config.toml.*.tmp"))


def test_single_and_batch_writers_share_the_same_os_lock(tmp_path):
    p = tmp_path / "config.toml"
    lock = SingleInstanceLock(p.with_name(p.name + ".lock"))
    assert lock.acquire()
    try:
        with pytest.raises(ConfigEditBusyError):
            set_config_key(p, "stt", "language", "en")
        with pytest.raises(ConfigEditBusyError):
            set_config_keys_atomic(
                p,
                [ConfigChange("stt", "language", "zh")],
            )
    finally:
        lock.release()


def test_empty_batch_is_a_true_noop(tmp_path):
    p = tmp_path / "config.toml"

    assert set_config_keys_atomic(p, []) == ()
    assert not p.exists()
    assert not p.with_name(p.name + ".lock").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not a Windows contract")
def test_atomic_replace_preserves_existing_file_mode(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[stt]\nmodel = "base.en"\n', encoding="utf-8")
    p.chmod(0o640)

    set_config_keys_atomic(
        p,
        [ConfigChange("stt", "language", "en")],
    )

    assert stat.S_IMODE(p.stat().st_mode) == 0o640


def test_atomic_batch_repairs_a_utf8_bom_while_preserving_values(tmp_path):
    p = tmp_path / "config.toml"
    p.write_bytes(b'\xef\xbb\xbf[stt]\nmodel = "base.en"\n')

    set_config_keys_atomic(
        p,
        [ConfigChange("stt", "language", "en")],
    )

    raw = p.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    parsed = tomllib.loads(raw.decode("utf-8"))
    assert parsed["stt"]["model"] == "base.en"
    assert parsed["stt"]["language"] == "en"


def test_expected_revision_rejects_a_stale_plan_without_writing(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[stt]\nmodel = "base.en"\n', encoding="utf-8")
    revision = config_revision(p)

    p.write_text('[stt]\nmodel = "small"\n', encoding="utf-8")
    concurrent = p.read_bytes()

    with pytest.raises(ConfigEditConflictError, match="changed"):
        set_config_keys_atomic(
            p,
            [ConfigChange("stt", "language", "zh")],
            expected_revision=revision,
        )

    assert p.read_bytes() == concurrent


def test_missing_and_empty_files_have_different_revisions(tmp_path):
    p = tmp_path / "config.toml"
    missing = config_revision(p)
    p.write_bytes(b"")

    assert missing == "missing"
    assert config_revision(p) != missing
