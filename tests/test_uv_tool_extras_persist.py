"""A `uv tool install`ed feature dependency must survive `uv tool upgrade`.

Found on a real machine: `yazses features enable stt-parakeet` installed
`onnx-asr` via a bare `uv pip install --python <venv>`, which never touches the
`uv tool` receipt for the install. Clicking the tray's "Install update" (or
running `yazses update`, or `uv tool upgrade yazses` by hand) runs
`upgrade_command("uv") == ["uv", "tool", "upgrade", "yazses"]`, which rebuilds
the venv from exactly what the receipt lists — so the extra silently vanished,
and dictation fell back from Parakeet to a much smaller, less accurate Whisper
model with no error the user would ever see.

Reproduced for real, once, in an isolated `UV_TOOL_DIR` (not part of this
offline suite — it needs PyPI): `uv tool install yazses==2.36.0`, then
`uv pip install --python <that venv> 'onnx-asr[cpu,hub]'`, then
`uv tool upgrade yazses` printed `Modified yazses environment -
onnx-asr==0.12.0` and the package was gone — even on a no-op upgrade, because
the tool version was pinned. Re-installing the same extra via
`uv tool install --with 'onnx-asr[cpu,hub]>=0.12' yazses` instead recorded it
in `uv-receipt.toml`, and it survived both a no-op reconciliation and a real
`2.36.0 -> 2.37.1` upgrade.

These tests exercise the parsing/merging logic that makes `deps.install_packages`
take that second path automatically, entirely offline (mocked `subprocess.run`,
`shutil.which`, `sys.prefix`) — the real-`uv` proof above is not repeatable
without network and is not what these guard.
"""

from __future__ import annotations

from yazses.system import deps

_RECEIPT_PINNED = """
[tool]
requirements = [
    { name = "yazses", specifier = "==2.36.0" },
]
"""

_RECEIPT_WITH_ONE_EXTRA = """
[tool]
requirements = [
    { name = "yazses" },
    { name = "onnx-asr", extras = ["cpu", "hub"], specifier = ">=0.12" },
]
"""


# ---- detecting a uv-tool install -------------------------------------------


def test_no_receipt_when_uv_is_absent(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)
    assert deps._uv_tool_receipt() is None


def test_no_receipt_when_the_prefix_does_not_match(monkeypatch, tmp_path):
    """The common case: a dev checkout's `.venv`, or a pipx install."""
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(
        deps.subprocess, "run",
        lambda *a, **k: type("R", (), {"stdout": str(tmp_path / "tools") + "\n"})(),
    )
    monkeypatch.setattr(deps.sys, "prefix", str(tmp_path / "some-other-venv"))
    assert deps._uv_tool_receipt() is None


def test_receipt_found_when_the_prefix_matches_the_tool_dir(monkeypatch, tmp_path):
    tool_dir = tmp_path / "tools"
    env_dir = tool_dir / "yazses"
    env_dir.mkdir(parents=True)
    receipt = env_dir / "uv-receipt.toml"
    receipt.write_text(_RECEIPT_PINNED, encoding="utf-8")

    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(
        deps.subprocess, "run",
        lambda *a, **k: type("R", (), {"stdout": str(tool_dir) + "\n"})(),
    )
    monkeypatch.setattr(deps.sys, "prefix", str(env_dir))

    assert deps._uv_tool_receipt() == receipt


def test_no_receipt_when_uv_tool_dir_fails(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/uv")

    def boom(*a, **k):
        raise deps.subprocess.CalledProcessError(1, a)

    monkeypatch.setattr(deps.subprocess, "run", boom)
    assert deps._uv_tool_receipt() is None


# ---- rendering / naming requirements ---------------------------------------


def test_requirement_name_strips_extras_and_specifier():
    assert deps._requirement_name("onnx-asr[cpu,hub]>=0.12") == "onnx-asr"
    assert deps._requirement_name("useful-moonshine-onnx") == "useful-moonshine-onnx"


def test_requirement_name_canonicalises_like_pypi():
    """Underscore, dot and dash all mean the same separator on PyPI."""
    assert deps._requirement_name("onnx_asr>=0.12") == "onnx-asr"
    assert deps._requirement_name("Onnx.Asr") == "onnx-asr"


def test_render_requirement_round_trips_extras_and_specifier():
    entry = {"name": "onnx-asr", "extras": ["cpu", "hub"], "specifier": ">=0.12"}
    assert deps._render_requirement(entry) == "onnx-asr[cpu,hub]>=0.12"


def test_render_requirement_with_no_extras_or_specifier():
    assert deps._render_requirement({"name": "yazses"}) == "yazses"


# ---- the merge that keeps a previous extra when a new one is enabled -------


def test_persist_adds_a_new_extra_and_keeps_the_pinned_target(monkeypatch, tmp_path):
    """The exact shape of the real incident: a version-pinned install."""
    receipt = tmp_path / "uv-receipt.toml"
    receipt.write_text(_RECEIPT_PINNED, encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        deps.subprocess, "run", lambda cmd, check: calls.append(cmd) or None
    )

    assert deps._persist_uv_tool_extras(receipt, ["onnx-asr[cpu,hub]>=0.12"]) is True

    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[:3] == ["uv", "tool", "install"]
    assert cmd[-1] == "yazses==2.36.0", "must not silently drop the version pin"
    assert "--with" in cmd
    assert cmd[cmd.index("--with") + 1] == "onnx-asr[cpu,hub]>=0.12"


def test_persist_keeps_a_previously_recorded_extra_when_adding_a_second(
    monkeypatch, tmp_path
):
    """The bug a naive fix would introduce: `--with X` REPLACES the with-list,
    it does not add to it — proven against the real `uv` CLI in session (enabling
    a second feature dropped the first). The merge here must read the receipt's
    existing requirements and reissue the union.
    """
    receipt = tmp_path / "uv-receipt.toml"
    receipt.write_text(_RECEIPT_WITH_ONE_EXTRA, encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        deps.subprocess, "run", lambda cmd, check: calls.append(cmd) or None
    )

    assert deps._persist_uv_tool_extras(receipt, ["useful-moonshine-onnx"]) is True

    withs = [c for c in calls[0] if "onnx" in c.lower()]
    assert "onnx-asr[cpu,hub]>=0.12" in withs, "the pre-existing extra was dropped"
    assert "useful-moonshine-onnx" in withs


def test_persist_replaces_a_requirement_of_the_same_package_rather_than_duplicating(
    monkeypatch, tmp_path
):
    """Re-enabling the same feature (or bumping its pin) must not produce two
    `--with` entries for one distribution, which `uv tool install` would reject
    as conflicting requirements."""
    receipt = tmp_path / "uv-receipt.toml"
    receipt.write_text(_RECEIPT_WITH_ONE_EXTRA, encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        deps.subprocess, "run", lambda cmd, check: calls.append(cmd) or None
    )

    assert deps._persist_uv_tool_extras(receipt, ["onnx-asr[cpu,hub]>=0.13"]) is True

    withs = [c for c in calls[0] if deps._requirement_name(c) == "onnx-asr"]
    assert withs == ["onnx-asr[cpu,hub]>=0.13"]


def test_persist_returns_false_on_an_unreadable_receipt(tmp_path):
    assert deps._persist_uv_tool_extras(tmp_path / "missing.toml", ["pkg"]) is False


def test_persist_returns_false_on_a_malformed_receipt(tmp_path):
    receipt = tmp_path / "uv-receipt.toml"
    receipt.write_text("not valid toml [[[", encoding="utf-8")
    assert deps._persist_uv_tool_extras(receipt, ["pkg"]) is False


def test_persist_returns_false_when_uv_tool_install_fails(monkeypatch, tmp_path):
    receipt = tmp_path / "uv-receipt.toml"
    receipt.write_text(_RECEIPT_PINNED, encoding="utf-8")

    def boom(cmd, check):
        raise deps.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(deps.subprocess, "run", boom)
    assert deps._persist_uv_tool_extras(receipt, ["pkg"]) is False


# ---- install_packages actually takes this path when it applies ------------


def test_install_packages_persists_via_the_uv_tool_receipt_when_present(
    monkeypatch, tmp_path
):
    receipt = tmp_path / "uv-receipt.toml"
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: receipt)
    monkeypatch.setattr(deps, "_persist_uv_tool_extras", lambda r, pkgs: r == receipt)

    def must_not_run(*a, **k):
        raise AssertionError("must not fall back to the plain install path")

    monkeypatch.setattr(deps, "install_command", must_not_run)
    monkeypatch.setattr(deps.subprocess, "run", must_not_run)

    assert deps.install_packages(["onnx-asr[cpu,hub]>=0.12"], echo=lambda *_: None) is True


def test_install_packages_falls_back_when_persisting_fails(monkeypatch, tmp_path):
    """Enabling the feature must still work this session even if recording it
    for next time does not — a `False` here is a worse update experience, not a
    broken one."""
    receipt = tmp_path / "uv-receipt.toml"
    monkeypatch.setattr(deps, "_uv_tool_receipt", lambda: receipt)
    monkeypatch.setattr(deps, "_persist_uv_tool_extras", lambda r, pkgs: False)
    calls = []
    monkeypatch.setattr(deps.subprocess, "run", lambda cmd, check: calls.append(cmd))

    said: list[str] = []
    assert deps.install_packages(["pkg"], echo=said.append) is True
    assert calls, "must still install into the current interpreter"
    assert any("may not survive" in m for m in said)
