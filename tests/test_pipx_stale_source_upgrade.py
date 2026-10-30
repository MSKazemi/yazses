"""A pipx install whose source folder was deleted must still be able to update itself.

``pipx install /path/to/checkout`` records that *path* as the package source in
``pipx_metadata.json``. Once the checkout (a git worktree, a build directory) is gone,
``pipx upgrade yazses`` prints ``Unable to parse package spec: <path>`` and changes
nothing -- on some pipx versions with exit 0 -- so the tray's "Install now" ran, the
version did not move, and the user was told to "reinstall the way you first installed".

Reproduced against pipx 1.4.3 in a throwaway PIPX_HOME: after the source was deleted,
``pipx upgrade`` failed, and ``pipx install --force yazses`` repaired the venv in place,
rewrote the source to the PyPI name and left a working ``pipx upgrade`` behind.
"""

from __future__ import annotations

import json
from pathlib import Path

from yazses.system import updater
from yazses.system.updater import UpdateStatus, resolve_upgrade_command


def _venv(tmp_path: Path, package_or_url: str) -> Path:
    prefix = tmp_path / "venvs" / "yazses"
    prefix.mkdir(parents=True)
    (prefix / "pipx_metadata.json").write_text(
        json.dumps({"main_package": {"package": "yazses", "package_or_url": package_or_url}}),
        encoding="utf-8",
    )
    return prefix


def _status(method: str = "pipx") -> UpdateStatus:
    return UpdateStatus(
        method=method, current="2.43.1", latest="2.45.0", available=True,
        command=updater.upgrade_command(method), note="", steps=[],
    )


def test_a_deleted_source_folder_becomes_a_reinstall_from_pypi(tmp_path):
    prefix = _venv(tmp_path, str(tmp_path / "gone-worktree") + "[gaze,desktop]")

    out = resolve_upgrade_command(_status(), pipx_prefix=str(prefix))

    assert out.command == ["pipx", "install", "--force", "yazses[gaze,desktop]"]


def test_a_deleted_source_without_extras_reinstalls_the_bare_name(tmp_path):
    prefix = _venv(tmp_path, str(tmp_path / "gone-worktree"))

    out = resolve_upgrade_command(_status(), pipx_prefix=str(prefix))

    assert out.command == ["pipx", "install", "--force", "yazses"]


def test_a_file_url_to_a_deleted_folder_is_stale_too(tmp_path):
    gone = (tmp_path / "gone").as_posix()
    prefix = _venv(tmp_path, f"yazses[desktop] @ file://{gone}")

    out = resolve_upgrade_command(_status(), pipx_prefix=str(prefix))

    assert out.command == ["pipx", "install", "--force", "yazses[desktop]"]


def test_extras_that_are_not_extra_names_leave_the_command_alone(tmp_path):
    """The extras are copied into the pipx command. A damaged record whose bracket holds
    more than extra names (here a stray `]` and a URL) must not reach it."""
    prefix = _venv(tmp_path, str(tmp_path / "gone") + "[desktop]@https://example.invalid/x.whl]")

    out = resolve_upgrade_command(_status(), pipx_prefix=str(prefix))

    assert out.command == updater.upgrade_command("pipx")

def test_a_pypi_install_keeps_the_plain_upgrade(tmp_path):
    for spec in ("yazses", "yazses[desktop]", "Yazses[gaze,desktop]"):
        prefix = _venv(tmp_path / spec.replace("[", "_").replace("]", "_"), spec)
        out = resolve_upgrade_command(_status(), pipx_prefix=str(prefix))
        assert out.command == ["pipx", "upgrade", "yazses"], spec


def test_a_source_that_still_exists_is_a_deliberate_choice(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    prefix = _venv(tmp_path, f"{checkout}[desktop]")

    out = resolve_upgrade_command(_status(), pipx_prefix=str(prefix))

    assert out.command == ["pipx", "upgrade", "yazses"]


def test_a_git_url_source_is_left_alone(tmp_path):
    prefix = _venv(tmp_path, "git+https://github.com/MSKazemi/yazses.git")

    out = resolve_upgrade_command(_status(), pipx_prefix=str(prefix))

    assert out.command == ["pipx", "upgrade", "yazses"]


def test_no_metadata_or_unreadable_metadata_changes_nothing(tmp_path):
    missing = tmp_path / "nothing-here"
    missing.mkdir()
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "pipx_metadata.json").write_text("{not json", encoding="utf-8")

    for prefix in (missing, broken):
        out = resolve_upgrade_command(_status(), pipx_prefix=str(prefix))
        assert out.command == ["pipx", "upgrade", "yazses"]


def test_other_methods_are_never_rewritten(tmp_path):
    prefix = _venv(tmp_path, str(tmp_path / "gone"))

    for method in ("pip", "snap"):
        before = _status(method)
        out = resolve_upgrade_command(before, pipx_prefix=str(prefix))
        assert out.command == before.command, method


def test_resolving_twice_is_idempotent(tmp_path):
    prefix = _venv(tmp_path, str(tmp_path / "gone") + "[desktop]")

    once = resolve_upgrade_command(_status(), pipx_prefix=str(prefix))
    twice = resolve_upgrade_command(once, pipx_prefix=str(prefix))

    assert twice.command == once.command


def test_the_failure_hint_for_pipx_names_the_reinstall():
    hint = updater.pinned_install_hint("pipx", ["pipx", "upgrade", "yazses"])

    assert "pipx install --force" in hint
    assert "Reinstall YazSes the way you first installed it" not in hint
