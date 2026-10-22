"""`yazses features repair` lists every dormant feature, asks once, and installs them.

A feature can be switched on while its libraries are missing (`◐ ON`): config edited
by hand, `--no-install`, or an update that rebuilt the environment. `features repair`
is the one command for the whole set. It must:

* plan before it acts — which features an install can fix here, which it cannot — in
  a pure function (`ondemand.repair_plan`), tested here without a probe or installer;
* install through the exact path `features install` uses (`ondemand.install_all` →
  `deps.install_feature`, which picks `uv tool`, `pipx inject` or the venv itself),
  so this file replaces `deps.install_feature` and nothing is fetched;
* refuse, in the same words as `features install`, where nothing can be installed (a
  snap, a frozen `.app`/`.exe`);
* end with one line per feature and exit non-zero unless every one was repaired.
"""

from __future__ import annotations

import types

from typer.testing import CliRunner

import yazses.cli as cli
from yazses.system import deps, dormant, ondemand

runner = CliRunner()


def _item(slug="denoise", *, installable=True, packages=("noisereduce>=3.0.3",)):
    return dormant.DormantFeature(
        slug=slug, name=slug.title(), missing=("noisereduce",),
        packages=tuple(packages),
        remedy="Install them with:  yazses features enable " + slug if installable
        else "this is a frozen bundle, whose payload is fixed when it is built",
        installable=installable,
        command=f"yazses features enable {slug}",
    )


# ---- the plan is pure --------------------------------------------------------------------


def test_the_plan_splits_what_can_install_from_what_cannot():
    plan = ondemand.repair_plan([_item("denoise"), _item("gaze", installable=False)])
    assert [d.slug for d in plan.install] == ["denoise"]
    assert [d.slug for d in plan.blocked] == ["gaze"]
    assert not plan.empty


def test_an_empty_plan_is_empty():
    plan = ondemand.repair_plan([])
    assert plan.empty and plan.install == () and plan.blocked == ()
    assert ondemand.repair_text(plan) == ""


def test_a_feature_listed_twice_is_planned_once():
    plan = ondemand.repair_plan([_item("denoise"), _item("denoise")])
    assert [d.slug for d in plan.install] == ["denoise"]


def test_the_listing_names_every_feature_and_its_packages(monkeypatch):
    monkeypatch.setattr("yazses.system.depsize.download_note", lambda slug, missing: "")
    plan = ondemand.repair_plan([_item("denoise"), _item("gaze", installable=False)])
    text = ondemand.repair_text(plan)
    assert "Denoise [denoise]: noisereduce>=3.0.3" in text
    assert "Gaze [gaze]" in text and "cannot fix it here" in text, (
        "a feature no install can fix is still listed; the list is the whole truth"
    )


def test_the_summary_says_what_happened_to_each_feature():
    plan = ondemand.repair_plan(
        [_item("denoise"), _item("prosody"), _item("gaze", installable=False)]
    )
    lines = ondemand.repair_summary(plan, ["prosody"])
    assert lines[0] == f"  Denoise [denoise]: {ondemand.REPAIRED}"
    assert lines[1].startswith(f"  Prosody [prosody]: {ondemand.FAILED}")
    assert "Retry:  yazses features enable prosody" in lines[1]
    assert lines[2].startswith(f"  Gaze [gaze]: {ondemand.BLOCKED}")
    assert len(lines) == 3


def test_the_exit_code_is_zero_only_when_everything_was_repaired():
    ok = ondemand.repair_plan([_item("denoise")])
    assert ondemand.repair_exit_code(ok, []) == 0
    assert ondemand.repair_exit_code(ok, ["denoise"]) == 1
    blocked = ondemand.repair_plan([_item("gaze", installable=False)])
    assert ondemand.repair_exit_code(blocked, []) == 1
    assert ondemand.repair_exit_code(ondemand.repair_plan([]), []) == 0


# ---- `yazses features repair` ------------------------------------------------------------


def _cli(monkeypatch, tmp_path, items, *, fail=()):
    """The idiom of tests/test_ondemand_install.py: stand-ins for the probe and installer."""
    monkeypatch.setattr(
        cli, "get_platform",
        lambda: types.SimpleNamespace(paths=types.SimpleNamespace(
            config_file=tmp_path / "config.toml")),
    )
    monkeypatch.setattr(dormant, "dormant_features", lambda cfg: list(items))
    monkeypatch.setattr("yazses.system.depsize.download_note", lambda slug, missing: "")
    calls: list = []

    def install(packages, *, check_modules=(), echo=print):
        calls.append(tuple(packages))
        return tuple(packages) not in fail

    monkeypatch.setattr(deps, "install_feature", install)
    return calls


def test_nothing_dormant_is_a_quiet_success(monkeypatch, tmp_path):
    calls = _cli(monkeypatch, tmp_path, [])
    result = runner.invoke(cli.app, ["features", "repair"])
    assert result.exit_code == 0 and calls == []
    assert "Nothing to repair" in result.output


def test_dry_run_lists_and_installs_nothing(monkeypatch, tmp_path):
    calls = _cli(monkeypatch, tmp_path, [_item("denoise"), _item("prosody")])
    result = runner.invoke(cli.app, ["features", "repair", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert calls == []
    assert "Denoise [denoise]" in result.output and "Prosody [prosody]" in result.output
    assert "noisereduce>=3.0.3" in result.output
    assert "[y/N]" not in result.output, "a dry run asks nothing"
    assert "nothing was installed" in result.output


def test_one_question_then_every_feature_is_installed(monkeypatch, tmp_path):
    calls = _cli(monkeypatch, tmp_path, [_item("denoise"), _item("prosody")])
    result = runner.invoke(cli.app, ["features", "repair"], input="y\n")
    assert result.exit_code == 0, result.output
    assert len(calls) == 2
    assert result.output.count("Install them now?") == 1, "one confirmation for the set"
    assert f"Denoise [denoise]: {ondemand.REPAIRED}" in result.output
    assert f"Prosody [prosody]: {ondemand.REPAIRED}" in result.output
    assert "yazses restart" in result.output


def test_no_at_the_question_installs_nothing(monkeypatch, tmp_path):
    calls = _cli(monkeypatch, tmp_path, [_item()])
    result = runner.invoke(cli.app, ["features", "repair"], input="n\n")
    assert result.exit_code == 1 and calls == []
    assert "Nothing installed" in result.output


def test_yes_does_not_ask(monkeypatch, tmp_path):
    calls = _cli(monkeypatch, tmp_path, [_item()])
    result = runner.invoke(cli.app, ["features", "repair", "--yes"])
    assert result.exit_code == 0, result.output
    assert calls and "[y/N]" not in result.output


def test_one_failure_does_not_stop_the_rest_and_fails_the_run(monkeypatch, tmp_path):
    calls = _cli(
        monkeypatch, tmp_path,
        [_item("denoise", packages=("noisereduce>=3.0.3",)),
         _item("prosody", packages=("parselmouth",))],
        fail={("noisereduce>=3.0.3",)},
    )
    result = runner.invoke(cli.app, ["features", "repair", "--yes"])
    assert result.exit_code == 1, result.output
    assert len(calls) == 2, "the second feature is still attempted"
    assert f"Denoise [denoise]: {ondemand.FAILED}" in result.output
    assert f"Prosody [prosody]: {ondemand.REPAIRED}" in result.output


def test_every_install_failing_does_not_say_restart(monkeypatch, tmp_path):
    _cli(monkeypatch, tmp_path, [_item()], fail={("noisereduce>=3.0.3",)})
    result = runner.invoke(cli.app, ["features", "repair", "--yes"])
    assert result.exit_code == 1
    assert "Apply it:  yazses restart" not in result.output


def test_a_frozen_install_refuses_with_the_features_install_message(monkeypatch, tmp_path):
    """Same words as `features install` gives there, and nothing is attempted."""
    item = _item("gaze", installable=False)
    calls = _cli(monkeypatch, tmp_path, [item])
    repaired = runner.invoke(cli.app, ["features", "repair", "--yes"])
    installed = runner.invoke(cli.app, ["features", "install", "--yes"])
    assert repaired.exit_code == 1 and calls == []
    refusal = f"Can't install for {item.name}: {item.remedy}"
    assert refusal in installed.output, "the reference message moved; update this test"
    assert refusal in repaired.output
    assert "[y/N]" not in repaired.output, "nothing to ask about when nothing can install"


def test_a_blocked_feature_fails_the_run_even_when_the_rest_install(monkeypatch, tmp_path):
    calls = _cli(monkeypatch, tmp_path, [_item("denoise"), _item("gaze", installable=False)])
    result = runner.invoke(cli.app, ["features", "repair", "--yes"])
    assert result.exit_code == 1, result.output
    assert calls == [("noisereduce>=3.0.3",)]
    assert f"Denoise [denoise]: {ondemand.REPAIRED}" in result.output
    assert f"Gaze [gaze]: {ondemand.BLOCKED}" in result.output


def test_repair_installs_through_the_features_install_path(monkeypatch, tmp_path):
    """Reuse, not a second installer: the plan's features go to `ondemand.install_all`,
    which is what `features install` calls (and which reaches `deps.install_feature`,
    the module ADR-019 registers for `uv` / `pip` / `pipx inject`)."""
    _cli(monkeypatch, tmp_path, [_item("denoise")])
    seen: list = []

    def install_all(items, *, install=None, echo=print):
        seen.append([d.slug for d in items])
        return []

    monkeypatch.setattr(ondemand, "install_all", install_all)
    result = runner.invoke(cli.app, ["features", "repair", "--yes"])
    assert result.exit_code == 0, result.output
    assert seen == [["denoise"]]


def test_repair_has_help_with_examples():
    result = runner.invoke(cli.app, ["features", "repair", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.output and "--yes" in result.output
    assert "Example" in result.output
