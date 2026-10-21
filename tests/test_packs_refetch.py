"""Add-ons across an update (ADR-028 Q3): consent at the update question, the download on
the new version's first start, and the one-click fallback when it does not happen.

* the update question names the installed packs and their sizes -- dialog text only,
  ``all_users`` and ``ALL_USERS_NOTE`` unchanged;
* the state machine: consented / not consented / failed / partial, with fakes;
* nothing is ever downloaded without a consent, and a consent is used at most once;
* the previous build's trees are deleted only after every new tree verified.

Offline: the install and the verify are fakes; layouts live in ``tmp_path``.
"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

import yazses.system.installer_update as iu
from tests.packs_fixtures import BUILD_ID, OTHER_BUILD_ID, FakeRuntime, base, entry_dict, index_dict
from yazses.packs import refetch as rf
from yazses.packs.context import PackContext, read_state, write_state
from yazses.packs.install import InstallResult
from yazses.packs.layout import COMPLETE, PackLayout, build_dir_name
from yazses.packs.manifest import parse_index
from yazses.packs.policy import Capability
from yazses.packs.state import TreeFact, empty_state, record_install, started_ok
from yazses.system.updater import UpdateStatus, manual_update_steps

NEW_DIR = build_dir_name(BUILD_ID, {})
OLD_DIR = build_dir_name(OTHER_BUILD_ID, {})
NOW = 1_000_000.0


def _status(method="windows-installer", **kw):
    data = dict(method=method, current="2.43.2", latest="2.44.0", available=True,
                command=None, note="", steps=manual_update_steps(method))
    data.update(kw)
    return UpdateStatus(**data)


def _index(*names: str, build_id: str = BUILD_ID):
    entries = [entry_dict(n, size=15_000_000 if n == "diarization" else 312_345)
               for n in names or ("parakeet",)]
    return parse_index(json.dumps(index_dict(*entries, base_build_id=build_id)))


def _ctx(tmp_path, *names: str, capable: bool = True, build_id: str = BUILD_ID) -> PackContext:
    layout = PackLayout.under(tmp_path / "data")
    return PackContext(
        runtime=FakeRuntime(),
        layout=layout,
        frozen=True,
        capability=Capability(True) if capable else Capability(False, "no", "elevated"),
        index=_index(*names, build_id=build_id),
        base=base(build_id),
        doc=read_state(layout),
    )


def _old_build(ctx: PackContext, *names: str) -> None:
    """What the previous version left: a tree per pack under the old build, recorded."""
    doc = empty_state()
    old = _index(*names, build_id=OTHER_BUILD_ID)
    for entry in old.packs:
        tree = ctx.layout.pack_dir(OLD_DIR, entry.name)
        tree.mkdir(parents=True)
        (tree / COMPLETE).write_text(f"sha256 {entry.sha256}\n", encoding="utf-8")
        doc = record_install(doc, component=OLD_DIR, build_id=OTHER_BUILD_ID,
                             app_version="2.43.2", entry=entry, at=100.0)
    write_state(ctx.layout, doc)


def _consent(ctx: PackContext, *names: str, at: float = NOW - 60, build_id=OTHER_BUILD_ID):
    rf.write_consent(ctx.layout, rf.Consent(build_id, "2.43.2", "2.44.0", names, at))


class _Fakes:
    """An install that writes what the real one writes (tree + state.json), and a verify."""

    def __init__(self, *, fail=(), bad=()):
        self.fail, self.bad = set(fail), set(bad)
        self.installs: list[str] = []
        self.docs: list[dict] = []
        self.verified: list[str] = []
        self.retired = 0

    def install(self, ctx: PackContext, entry):
        self.installs.append(entry.name)
        self.docs.append(ctx.doc)
        if entry.name in self.fail:
            return InstallResult(False, "Add-on not installed",
                                 "Couldn't reach github.com.", step="download")
        tree = ctx.layout.pack_dir(NEW_DIR, entry.name)
        tree.mkdir(parents=True)
        (tree / COMPLETE).write_text(f"sha256 {entry.sha256}\n", encoding="utf-8")
        write_state(ctx.layout, record_install(
            ctx.doc, component=NEW_DIR, build_id=BUILD_ID, app_version="2.44.0",
            entry=entry, at=200.0 + len(self.installs)))
        return InstallResult(True, "installed", "ok", step="done")

    def verify(self, ctx: PackContext, name: str):
        self.verified.append(name)
        return [(name, "a file is missing")] if name in self.bad else []

    def run(self, ctx, **kw):
        return rf.run_refetch(ctx, now=lambda: NOW, install=self.install,
                              verify=self.verify, **kw)


# ---- 1. the update question -----------------------------------------------------------

def test_the_question_names_the_installed_addons_and_their_sizes():
    _t, text = iu.confirmation_prompt(_status(), addons=[("diarization", 15_000_000)])
    assert ("Your add-on (Diarization, 15 MB) will be downloaded again for the new "
            "version.") in text
    assert "Install now" in text
    _t, text = iu.confirmation_prompt(
        _status(), addons=[("diarization", 15_000_000), ("voice-activity", 2_000_000)])
    assert "Your add-ons (Diarization, 15 MB; Voice Activity, 2.0 MB)" in text


def test_without_addons_the_question_is_unchanged():
    assert iu.confirmation_prompt(_status()) == iu.confirmation_prompt(_status(), addons=())
    _t, text = iu.confirmation_prompt(_status())
    assert "add-on" not in text


def test_the_all_users_note_is_untouched_by_the_addons_line():
    _t, text = iu.confirmation_prompt(_status(), all_users=True,
                                      addons=[("diarization", 15_000_000)])
    assert iu.ALL_USERS_NOTE in text and "Windows PowerShell" in text
    assert "Diarization, 15 MB" in text
    _t, text = iu.confirmation_prompt(_status(), addons=[("diarization", 15_000_000)])
    assert iu.ALL_USERS_NOTE not in text


def test_the_addons_line_never_reaches_the_offer_reason():
    # Offer.reason rides a tray balloon (Windows drops it whole over 255 chars): the
    # add-ons sentence lives in the dialog only.
    import inspect

    assert "addons" not in inspect.signature(iu.one_click_offer).parameters
    assert "addons" not in {f.name for f in iu.Offer.__dataclass_fields__.values()}


def test_installed_addons_lists_only_intact_trees_in_index_order():
    index = _index("parakeet", "diarization")
    trees = {"diarization": TreeFact("ok"), "parakeet": TreeFact("damaged", "x")}
    assert rf.installed_addons(index, trees) == (("diarization", 15_000_000),)
    assert rf.installed_addons(None, trees) == ()


# ---- 2. the consent record --------------------------------------------------------------

def test_consent_round_trips_and_garbage_is_no_consent():
    c = rf.Consent(OTHER_BUILD_ID, "2.43.2", "2.44.0", ("diarization",), NOW)
    assert rf.parse_consent(rf.dump_consent(c)) == c
    for bad in (None, "", "{", "[]", '{"format": 2}',
                json.dumps({"format": 1, "build_id": "x", "packs": [], "at": 1}),
                json.dumps({"format": 1, "build_id": "x", "packs": ["a"], "at": True})):
        assert rf.parse_consent(bad) is None


def test_record_consent_writes_nothing_when_the_question_named_no_addon(tmp_path):
    ctx = _ctx(tmp_path)
    assert rf.record_consent(ctx, (), from_version="2.43.2", to_version="2.44.0") is False
    assert not rf.consent_pending(ctx.layout)
    assert rf.record_consent(ctx, [("parakeet", 1)], from_version="2.43.2",
                             to_version="2.44.0", now=lambda: NOW)
    assert rf.read_consent(ctx.layout) == rf.Consent(
        BUILD_ID, "2.43.2", "2.44.0", ("parakeet",), NOW)


# ---- 3. the decision ----------------------------------------------------------------------

def _plan(consent, *, capable=True, index=None, trees=None, doc=None, now=NOW):
    if doc is None:
        doc = record_install(empty_state(), component=OLD_DIR, build_id=OTHER_BUILD_ID,
                             app_version="2.43.2", entry=_index("parakeet").packs[0], at=1)
    return rf.plan_refetch(consent, now=now, capable=capable,
                           index=index or _index("parakeet"), trees=trees or {}, doc=doc)


def test_plan_without_consent_does_nothing():
    assert _plan(None).fetch == ()


def test_plan_fetches_what_the_user_had_and_this_build_offers():
    c = rf.Consent(OTHER_BUILD_ID, "2.43.2", "2.44.0", ("parakeet",), NOW - 5)
    assert _plan(c).fetch == ("parakeet",)


@pytest.mark.parametrize("why, kw, consent_kw", [
    ("stale", {}, {"at": NOW - rf.CONSENT_MAX_AGE_S - 1}),
    ("future", {}, {"at": NOW + 2 * 86400}),
    ("not capable", {"capable": False}, {}),
    ("same build (failed update)", {}, {"build_id": BUILD_ID}),
    ("not recorded in state.json", {"doc": empty_state()}, {}),
])
def test_plan_refuses(why, kw, consent_kw):
    data = dict(build_id=OTHER_BUILD_ID, from_version="2.43.2", to_version="2.44.0",
                packs=("parakeet",), at=NOW - 5)
    data.update(consent_kw)
    assert _plan(rf.Consent(**data), **kw).fetch == (), why


def test_plan_skips_packs_this_build_no_longer_offers_or_already_has():
    doc = empty_state()
    for e in _index("parakeet", "diarization", "gaze").packs:
        doc = record_install(doc, component=OLD_DIR, build_id=OTHER_BUILD_ID,
                             app_version="2.43.2", entry=e, at=1)
    c = rf.Consent(OTHER_BUILD_ID, "2.43.2", "2.44.0", ("parakeet", "diarization", "gaze"),
                   NOW)
    plan = _plan(c, index=_index("diarization", "gaze"), doc=doc,
                 trees={"gaze": TreeFact("ok")})
    assert plan.fetch == ("diarization",)
    assert plan.not_offered == ("parakeet",) and plan.present == ("gaze",)


# ---- 4. the first start: the state machine --------------------------------------------

def test_no_consent_never_downloads(tmp_path):
    ctx = _ctx(tmp_path, "parakeet")
    _old_build(ctx, "parakeet")
    fakes = _Fakes()
    out = fakes.run(ctx, retire=lambda c: [])
    assert out.state == rf.DORMANT and fakes.installs == []
    assert rf.describe(out) is None
    assert ctx.layout.build_dir(OLD_DIR).is_dir()


# ---- 4b. the first good start writes started_ok and retires the old build ---------------

def test_a_first_start_with_nothing_to_download_marks_it_and_retires_the_old_build(tmp_path):
    # Nothing else writes started_ok: without this the old build's packs stayed forever.
    ctx = _ctx(tmp_path, "parakeet")
    _old_build(ctx, "parakeet")
    out = _Fakes().run(ctx)
    assert out.state == rf.DORMANT and out.retired == (OLD_DIR,)
    assert not ctx.layout.build_dir(OLD_DIR).exists()
    doc = read_state(ctx.layout)
    assert started_ok(doc, BUILD_ID) and OLD_DIR not in doc["builds"]
    assert rf.describe(out) is None


def test_the_marker_is_written_once_per_build(tmp_path):
    ctx = _ctx(tmp_path, "parakeet")
    _old_build(ctx, "parakeet")
    # This build has an add-on too, so state.json still lists a build after the retire
    # and only the started_ok check can stop a second one.
    write_state(ctx.layout, record_install(
        read_state(ctx.layout), component=NEW_DIR, build_id=BUILD_ID, app_version="2.44.0",
        entry=ctx.index.packs[0], at=300.0))
    calls: list = []

    def retire(c):
        calls.append(c)
        return rf.retire_old_builds(c)

    fakes = _Fakes()
    fakes.run(ctx, retire=retire)
    fakes.run(ctx, retire=retire)
    assert len(calls) == 1


def test_no_add_on_ever_installed_writes_no_state(tmp_path):
    ctx = _ctx(tmp_path, "parakeet")
    assert _Fakes().run(ctx).retired == ()
    assert not ctx.layout.state_file.exists()


def test_a_failed_refetch_retires_nothing_and_the_next_start_retires_the_old_build(tmp_path):
    ctx = _ctx(tmp_path, "diarization")
    _old_build(ctx, "diarization")
    _consent(ctx, "diarization")
    fakes = _Fakes(fail={"diarization"})
    assert fakes.run(ctx).state == rf.FAILED
    assert ctx.layout.build_dir(OLD_DIR).is_dir()
    assert not started_ok(read_state(ctx.layout), BUILD_ID)
    # Next start: nothing consented any more, so nothing is downloaded -- and the old
    # build, which this build cannot load, is no longer kept for a rollback.
    again = fakes.run(ctx)
    assert again.state == rf.DORMANT and fakes.installs == ["diarization"]
    assert not ctx.layout.build_dir(OLD_DIR).exists()


def test_refetch_after_update_still_marks_the_start_without_a_consent(tmp_path):
    from yazses.tray.updates import refetch_after_update

    ctx = _ctx(tmp_path, "parakeet")
    _old_build(ctx, "parakeet")
    fakes = _Fakes()
    assert refetch_after_update(layout=ctx.layout, load=lambda: ctx,
                                install=fakes.install, verify=fakes.verify) is None
    assert fakes.installs == [] and not ctx.layout.build_dir(OLD_DIR).exists()
    assert started_ok(read_state(ctx.layout), BUILD_ID)


def test_consented_downloads_verifies_then_retires_the_old_build(tmp_path):
    ctx = _ctx(tmp_path, "parakeet", "diarization")
    _old_build(ctx, "parakeet", "diarization")
    _consent(ctx, "parakeet", "diarization")
    fakes = _Fakes()
    out = fakes.run(ctx)
    assert out.state == rf.DONE and out.installed == ("parakeet", "diarization")
    assert fakes.verified == ["parakeet", "diarization"]
    assert not rf.consent_pending(ctx.layout)
    assert not ctx.layout.build_dir(OLD_DIR).exists() and out.retired == (OLD_DIR,)
    doc = read_state(ctx.layout)
    assert started_ok(doc, BUILD_ID)
    assert set(doc["builds"]) == {NEW_DIR}
    assert set(doc["builds"][NEW_DIR]["packs"]) == {"parakeet", "diarization"}
    title, body = rf.describe(out)
    assert title == "Add-ons ready" and "Parakeet and Diarization" in body
    assert "2.44.0" in body and "Restart YazSes" in body and len(body) < 255


def test_each_install_gets_the_state_the_previous_one_wrote(tmp_path):
    # install_pack rewrites state.json from the document it is handed: a stale one would
    # forget the pack installed just before it.
    ctx = _ctx(tmp_path, "parakeet", "diarization")
    _old_build(ctx, "parakeet", "diarization")
    _consent(ctx, "parakeet", "diarization")
    fakes = _Fakes()
    fakes.run(ctx, retire=lambda c: [])
    assert "parakeet" in fakes.docs[1]["builds"][NEW_DIR]["packs"]


def test_a_failed_download_keeps_the_old_build_and_points_at_install_now(tmp_path):
    ctx = _ctx(tmp_path, "diarization")
    _old_build(ctx, "diarization")
    _consent(ctx, "diarization")
    fakes = _Fakes(fail={"diarization"})
    out = fakes.run(ctx)
    assert out.state == rf.FAILED and out.failed[0][0] == "diarization"
    assert ctx.layout.build_dir(OLD_DIR).is_dir()
    assert not started_ok(read_state(ctx.layout), BUILD_ID)
    assert not rf.consent_pending(ctx.layout)
    title, body = rf.describe(out)
    assert title == "Add-ons not downloaded" and "Install now" in body
    assert "Diarization" in body and len(body) < 255


def test_partial_keeps_the_old_build_until_everything_verified(tmp_path):
    ctx = _ctx(tmp_path, "parakeet", "diarization")
    _old_build(ctx, "parakeet", "diarization")
    _consent(ctx, "parakeet", "diarization")
    retired: list = []
    fakes = _Fakes(fail={"diarization"})
    out = fakes.run(ctx, retire=lambda c: retired.append(c) or [])
    assert out.state == rf.PARTIAL and out.installed == ("parakeet",)
    assert retired == [] and ctx.layout.build_dir(OLD_DIR).is_dir()
    title, body = rf.describe(out)
    assert "Parakeet" in body and "Diarization" in body and "Install now" in body


def test_a_tree_that_fails_its_check_is_a_failure_and_retires_nothing(tmp_path):
    ctx = _ctx(tmp_path, "diarization")
    _old_build(ctx, "diarization")
    _consent(ctx, "diarization")
    fakes = _Fakes(bad={"diarization"})
    out = fakes.run(ctx)
    assert out.state == rf.FAILED and "missing" in out.failed[0][1]
    assert ctx.layout.build_dir(OLD_DIR).is_dir()


def test_a_consent_is_used_once_whatever_happened(tmp_path):
    for fail in (set(), {"diarization"}):
        ctx = _ctx(tmp_path / str(len(fail)), "diarization")
        _old_build(ctx, "diarization")
        _consent(ctx, "diarization")
        fakes = _Fakes(fail=fail)
        fakes.run(ctx, retire=lambda c: [])
        again = fakes.run(ctx, retire=lambda c: [])
        assert again.state == rf.DORMANT and fakes.installs == ["diarization"]


def test_a_consent_that_cannot_be_erased_downloads_nothing(tmp_path, monkeypatch):
    # Otherwise every start would repeat it.
    ctx = _ctx(tmp_path, "diarization")
    _old_build(ctx, "diarization")
    _consent(ctx, "diarization")
    monkeypatch.setattr(rf, "erase_consent", lambda layout: False)
    fakes = _Fakes()
    assert fakes.run(ctx).state == rf.DORMANT and fakes.installs == []


def test_a_failed_update_relaunching_the_old_build_drops_the_consent(tmp_path):
    ctx = _ctx(tmp_path, "diarization", build_id=OTHER_BUILD_ID)
    _old_build(ctx, "diarization")
    _consent(ctx, "diarization")
    fakes = _Fakes()
    out = fakes.run(ctx)
    assert out.state == rf.DORMANT and fakes.installs == []
    assert not rf.consent_pending(ctx.layout)
    assert ctx.layout.build_dir(OLD_DIR).is_dir()


def test_an_unreadable_consent_is_dropped_not_retried(tmp_path):
    ctx = _ctx(tmp_path, "diarization")
    ctx.layout.root.mkdir(parents=True)
    rf.consent_path(ctx.layout).write_text("{not json", encoding="utf-8")
    fakes = _Fakes()
    assert fakes.run(ctx).state == rf.DORMANT and fakes.installs == []
    assert not rf.consent_pending(ctx.layout)


def test_an_elevated_or_incapable_process_never_downloads_or_deletes(tmp_path):
    ctx = _ctx(tmp_path, "diarization", capable=False)
    _old_build(ctx, "diarization")
    _consent(ctx, "diarization")
    fakes = _Fakes()
    assert fakes.run(ctx).state == rf.DORMANT and fakes.installs == []
    assert ctx.layout.build_dir(OLD_DIR).is_dir()
    assert fakes.run(ctx).retired == ()


def test_an_install_that_raises_is_a_failure_not_a_crash(tmp_path):
    ctx = _ctx(tmp_path, "diarization")
    _old_build(ctx, "diarization")
    _consent(ctx, "diarization")

    def boom(c, e):
        raise RuntimeError("bug")

    out = rf.run_refetch(ctx, now=lambda: NOW, install=boom, verify=lambda c, n: [])
    assert out.state == rf.FAILED and ctx.layout.build_dir(OLD_DIR).is_dir()


# ---- 5. the tray: consent at the question, the job at startup ------------------------------

def test_refetch_after_update_loads_nothing_without_a_consent(tmp_path):
    from yazses.tray.updates import refetch_after_update

    layout = PackLayout.under(tmp_path / "data")

    def load():
        raise AssertionError("loaded the pack context without a consent")

    assert refetch_after_update(layout=layout, load=load, install=None, verify=None) is None


def test_refetch_after_update_runs_once_and_returns_the_message(tmp_path):
    from yazses.tray.updates import refetch_after_update

    ctx = _ctx(tmp_path, "diarization")
    _old_build(ctx, "diarization")
    _consent(ctx, "diarization")
    fakes = _Fakes()

    def run(c, **kw):
        return rf.run_refetch(c, now=lambda: NOW, retire=lambda x: [], **kw)

    for _ in range(2):
        msg = refetch_after_update(layout=ctx.layout, load=lambda: ctx, run=run,
                                   install=fakes.install, verify=fakes.verify)
        assert msg is None or msg[0] == "Add-ons ready"
    assert fakes.installs == ["diarization"]


def test_a_consent_this_install_cannot_act_on_is_erased(tmp_path):
    from yazses.tray.updates import refetch_after_update

    ctx = _ctx(tmp_path, "diarization")
    _consent(ctx, "diarization")
    assert refetch_after_update(layout=ctx.layout, load=lambda: None,
                                install=None, verify=None) is None
    assert not rf.consent_pending(ctx.layout)


def test_outside_a_frozen_build_the_tray_names_no_addons_and_records_nothing():
    from yazses.tray.updates import record_update_consent, update_addons

    assert update_addons() == ()
    assert record_update_consent(_status(), (("diarization", 1),)) is False


def _tray(monkeypatch, tmp_path, *, confirm=True, ok=True):
    import yazses.platform.windows.tray as wtray
    import yazses.tray.updates as tray_updates
    from tests.test_one_click_windows_update import FakeLauncher, _Icon

    recorded: list = []
    monkeypatch.setattr(tray_updates, "check_updates", lambda current=None: _status())
    monkeypatch.setattr(tray_updates, "update_addons", lambda: (("diarization", 15_000_000),))
    monkeypatch.setattr(tray_updates, "record_update_consent",
                        lambda status, addons: recorded.append((status.latest, addons)))
    monkeypatch.setattr(tray_updates, "run_one_click",
                        lambda st, la, progress=None: iu.HandoffResult(
                            ok=ok, title="Installing" if ok else "Update not installed",
                            message="bye"))
    monkeypatch.setattr(wtray, "open_link", lambda url: True)
    asked: list = []
    wtray._run_update(_Icon(), lambda _i, t, b: None, launcher=FakeLauncher(tmp_path),
                      confirm=lambda t, b: asked.append(b) or confirm, sleep=lambda s: None)
    return asked, recorded


def test_the_tray_question_names_the_addons_and_a_started_hand_off_records_the_yes(
        monkeypatch, tmp_path):
    asked, recorded = _tray(monkeypatch, tmp_path)
    assert "Your add-on (Diarization, 15 MB)" in asked[0]
    assert recorded == [("2.44.0", (("diarization", 15_000_000),))]


@pytest.mark.parametrize("confirm, ok", [(False, True), (True, False)])
def test_a_no_or_a_failed_hand_off_records_no_consent(monkeypatch, tmp_path, confirm, ok):
    _asked, recorded = _tray(monkeypatch, tmp_path, confirm=confirm, ok=ok)
    assert recorded == []


def test_the_refetch_context_keeps_its_own_index_not_the_old_one(tmp_path):
    # The new version installs against the index built into *it*: the context the job
    # gets is this process's, so the entries (and hashes) are the new build's.
    ctx = _ctx(tmp_path, "diarization")
    _old_build(ctx, "diarization")
    _consent(ctx, "diarization")
    seen: list = []

    def install(c, entry):
        seen.append((c.index.base_build_id, entry.sha256))
        return InstallResult(False, "x", "y")

    rf.run_refetch(replace(ctx), now=lambda: NOW, install=install, verify=lambda c, n: [])
    assert seen == [(BUILD_ID, ctx.index.packs[0].sha256)]


# ---- 6. where the downloader is bound ------------------------------------------------------

def test_the_tray_entry_point_binds_the_downloader_and_shows_the_result_once():
    import threading

    from yazses.tray import app

    class Tray:
        def __init__(self):
            self.shown = []

        def notify(self, title, body):
            self.shown.append((title, body))

    calls = []

    def refetch(*, install, verify):
        calls.append((install, verify))
        return ("Add-ons ready", "Diarization is downloaded again.")

    tray = Tray()
    app.start_addon_refetch(tray, threading.Event(), delay_s=0, refetch=refetch).join(5)
    assert calls == [(app._pack_install, app._pack_verify)]
    assert tray.shown == [("Add-ons ready", "Diarization is downloaded again.")]


def test_quitting_before_the_delay_runs_nothing():
    import threading

    from yazses.tray import app

    stop = threading.Event()
    stop.set()
    ran = []
    app.start_addon_refetch(object(), stop, delay_s=5,
                            refetch=lambda **kw: ran.append(kw)).join(5)
    assert ran == []


def test_refetch_has_no_downloader_of_its_own():
    # tray.updates (and so packs.refetch) is in the daemon's static import closure: a
    # default install here would put the download one import away from the daemon.
    import inspect

    params = inspect.signature(rf.run_refetch).parameters
    assert params["install"].default is inspect.Parameter.empty
    assert params["verify"].default is inspect.Parameter.empty
