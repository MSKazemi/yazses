"""The four capabilities wired by ADR-v2-131 that answer to *state*, not to a phrase.

The other six (`tests/test_spoken_capabilities_answer_to_a_phrase.py`) are triggered by
something the user says. These four are triggered by something about the machine: how
loaded it is, which window has focus, what you have corrected before. That difference is
why they need their own file — none of them can be tested by feeding a phrase in.

Each one is asserted three ways, because the failure this repo keeps hitting is a
capability that is *reachable* without being *effective*:

1. **Off by default it changes nothing.** A stock install must behave exactly as before.
2. **On, it does the thing.** With its precondition met, the observable output differs.
3. **Its precondition is real.** With the precondition missing it declines, and
   `features enable` says so rather than writing a config key with nothing behind it.

The daemon methods are exercised through `SimpleNamespace`, the same way
`test_cmdsafety_sees_the_typed_text.py` does: constructing a `Daemon` loads an STT model.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yazses.config import Config
from yazses.system.features import enable_caveat, unwired_slugs

WIRED = ("corrdict", "smartpaste", "focusprofile", "latency")


@pytest.mark.parametrize("slug", WIRED)
def test_the_registry_no_longer_calls_it_planned(slug: str) -> None:
    assert slug not in unwired_slugs()


# ---- corrdict: Self-Learning Correction Dictionary (ADR-v2-079) ----------


def test_a_correction_you_made_three_times_is_replayed() -> None:
    from yazses.corrdict.mine import apply_corrections
    from yazses.corrdict.table import build_table

    events = [
        SimpleNamespace(final_text="yaz says is offline", correction_text="YazSes is offline"),
        SimpleNamespace(final_text="I like yaz says a lot", correction_text="I like YazSes a lot"),
        SimpleNamespace(final_text="yaz says types", correction_text="YazSes types"),
    ]
    table = build_table(events, min_support=3)
    assert table == {"yaz says": "YazSes"}
    assert apply_corrections("tell them yaz says works", table) == "tell them YazSes works"


def test_two_corrections_are_not_enough() -> None:
    """`min_support` is the whole point: a table built from one slip fires forever."""
    from yazses.corrdict.table import build_table

    events = [
        SimpleNamespace(final_text="yaz says is offline", correction_text="YazSes is offline"),
        SimpleNamespace(final_text="yaz says types", correction_text="YazSes types"),
    ]
    assert build_table(events, min_support=3) == {}


def test_an_ambiguous_correction_is_dropped_rather_than_guessed() -> None:
    """Corrected to two different things equally often — so we do not know which."""
    from yazses.corrdict.table import build_table

    events = (
        [SimpleNamespace(final_text="the lead", correction_text="the led")] * 3
        + [SimpleNamespace(final_text="the lead", correction_text="the LED")] * 3
    )
    assert build_table(events, min_support=3) == {}


def test_a_rewrite_is_not_mined_as_a_recognition_error() -> None:
    """The guard on span length. Somebody rewording a sentence three times must not
    turn that rewording into an automatic substitution applied to other sentences."""
    from yazses.corrdict.table import build_table

    long_edit = SimpleNamespace(
        final_text="please send the document over to the team when you can",
        correction_text="please forward the file across to everyone at your convenience",
    )
    assert build_table([long_edit] * 5, min_support=3) == {}


def test_a_misrecognition_and_a_rewording_are_told_apart() -> None:
    """The measurement `corrdict/mine.py::similarity` documents, pinned at both ends.

    Without the similarity gate the rewrite case above mined `send -> forward` as
    cleanly as a real misrecognition, because difflib breaks a whole-sentence rewrite
    into exactly the short spans the length guard allows.
    """
    from yazses.corrdict.mine import MIN_SIMILARITY, similarity

    for wrong, right in [("yaz says", "YazSes"), ("cubernetties", "Kubernetes"),
                         ("affect", "effect"), ("there", "their"), ("week", "weak")]:
        assert similarity(wrong, right) >= MIN_SIMILARITY, (wrong, right)
    for wrong, right in [("send", "forward"), ("document over", "file across"),
                         ("to the team", "across to everyone")]:
        assert similarity(wrong, right) < MIN_SIMILARITY, (wrong, right)


def test_an_ordinary_corpus_of_successful_dictation_mines_nothing() -> None:
    """No correction, no table — which is why this is safe to leave on."""
    from yazses.corrdict.table import build_table

    events = [SimpleNamespace(final_text=f"sentence number {i}", correction_text="") for i in range(50)]
    assert build_table(events, min_support=3) == {}


def test_the_table_is_bounded() -> None:
    """Every entry is a regex run over every burst; an unbounded table is a latency cost."""
    from yazses.corrdict.table import build_table

    events = []
    for i in range(300):
        events += [SimpleNamespace(final_text=f"wrong{i} word", correction_text=f"right{i} word")] * 3
    table = build_table(events, min_support=3, max_entries=200)
    assert len(table) == 200


def test_corrdict_is_inert_without_the_learning_corpus() -> None:
    """The daemon's own cache, not the pure core: it must not even open a store."""
    from yazses.core.daemon import Daemon

    cfg = Config()
    cfg.corrdict.enabled = True
    assert cfg.learning.enabled is False
    warned: list[tuple[str, str]] = []
    fake = SimpleNamespace(
        _config=cfg,
        _correction_table_cache=None,
        _warn_feature_inert=lambda f, r: warned.append((f, r)),
        _platform=SimpleNamespace(paths=SimpleNamespace(data_dir=None)),
    )
    assert Daemon._correction_table(fake) == {}
    assert warned and warned[0][0] == "corrdict"
    assert "[learning] enabled is false" in warned[0][1]


def test_enabling_corrdict_alone_says_it_will_do_nothing() -> None:
    caveat = enable_caveat("corrdict", Config())
    assert caveat and "learning corpus" in caveat


# ---- smartpaste: Smart-Paste (ADR-v2-036) -------------------------------


@pytest.mark.parametrize(
    "app_class,expected",
    [
        ("obsidian", "- shopping list"),
        ("gnome-terminal", "• shopping list"),
        ("code", "• shopping list"),
        ("thunderbird", "• shopping list"),
    ],
)
def test_a_bullet_is_rewritten_only_where_that_is_the_convention(app_class, expected) -> None:
    from yazses.smartpaste.adapt import adapt, classify_surface

    assert adapt("• shopping list", classify_surface(app_class)) == expected


def test_a_shell_command_dictated_into_a_terminal_is_untouched() -> None:
    """The case that would be a bug rather than a cosmetic difference."""
    from yazses.smartpaste.adapt import adapt, classify_surface

    text = "curl https://example.com/install.sh"
    assert adapt(text, classify_surface("alacritty")) == text


def test_smartpaste_needs_the_focused_window_probe() -> None:
    cfg = Config()
    cfg.injection.target_guard = "off"
    caveat = enable_caveat("smartpaste", cfg)
    assert caveat and "target_guard" in caveat


# ---- focusprofile: Focus-Class Auto-Profile (ADR-v2-094) ----------------


@pytest.mark.parametrize(
    "app_class,klass",
    [("gnome-terminal", "shell"), ("nvim", "code"), ("firefox", "prose"), ("", None)],
)
def test_the_focus_class_maps_the_way_the_daemon_reads_it(app_class, klass) -> None:
    from yazses.focusprofile.resolve import resolve_profile

    assert resolve_profile("", app_class) == klass


def test_a_user_written_glob_still_wins() -> None:
    """The daemon only consults focusprofile when `[profiles.app]` matched nothing.

    Asserted on the resolver the daemon actually calls first, because "fills in"
    versus "overrides" is the difference between a helpful default and a setting
    the user cannot turn off for one app.
    """
    from yazses.postprocess.profiles import resolve_profile as app_profile

    cfg = Config()
    cfg.profiles.app = {"*terminal*": "casual"}
    assert app_profile("gnome-terminal", cfg.profiles).tone == "casual"


def test_focusprofile_needs_the_focused_window_probe() -> None:
    cfg = Config()
    cfg.injection.target_guard = "off"
    caveat = enable_caveat("focusprofile", cfg)
    assert caveat and "target_guard" in caveat


# ---- latency: Adaptive Latency Governor (ADR-v2-073) -------------------


def test_the_policy_follows_the_load() -> None:
    from yazses.latency.governor import LIGHT_BEAM, GovernorConfig, pick_policy

    cfg = GovernorConfig(base_model="base.en", light_model="tiny.en", draft_model="")
    assert pick_policy(95.0, cfg) == pick_policy(85.0, cfg)
    assert pick_policy(95.0, cfg).model == "tiny.en"
    # Asserted through the constant, not against a literal: its value is a
    # measurement (see `governor.LIGHT_BEAM`) and moved once already. What this
    # test is for is that the *policy* narrows the beam under load, which a
    # literal would restate as a coincidence and re-break on the next re-measure.
    assert pick_policy(95.0, cfg).beam_size == LIGHT_BEAM
    assert LIGHT_BEAM < 5, "the light policy must narrow the beam, not widen it"
    assert pick_policy(10.0, cfg).model == "base.en"
    assert pick_policy(10.0, cfg).speculative is False  # no draft model is wired


def test_the_pool_never_loads_on_the_hot_path() -> None:
    """The property that makes this a latency governor rather than a latency source."""
    from yazses.latency.pool import EnginePool

    built: list[tuple[str, int]] = []
    queued: list = []
    pool = EnginePool(
        lambda m, b: built.append((m, b)) or f"engine:{m}:{b}",
        ("base.en", 0),
        "engine:base.en:0",
        spawn=queued.append,
    )

    assert pool.get("base.en", 0) == "engine:base.en:0"  # already resident
    assert built == [] and queued == []

    assert pool.get("tiny.en", 1) is None                # not resident: decode as before
    assert built == []                                   # and nothing loaded inline
    assert len(queued) == 1

    assert pool.get("tiny.en", 1) is None                # a second burst does not queue twice
    assert len(queued) == 1

    queued[0]()                                          # the background load completes
    assert built == [("tiny.en", 1)]
    assert pool.get("tiny.en", 1) == "engine:tiny.en:1"


def test_a_model_that_cannot_load_is_not_retried_every_burst() -> None:
    from yazses.latency.pool import EnginePool

    calls: list = []

    def build(model, beam):
        calls.append(model)
        raise RuntimeError("no such model")

    queued: list = []
    pool = EnginePool(build, ("base.en", 0), "base", spawn=queued.append)
    pool.get("nonexistent", 1)
    queued[0]()
    assert calls == ["nonexistent"]
    assert pool.get("nonexistent", 1) is None
    assert len(queued) == 1, "a failed load was queued again"


def test_the_governor_declines_where_the_platform_cannot_answer(monkeypatch) -> None:
    """`None`, never 0.0 — an unreadable load is not an idle machine."""
    import yazses.latency.load as load

    monkeypatch.delattr(load.os, "getloadavg", raising=False)
    assert load.cpu_percent() is None
    assert "getloadavg" in (load.unavailable_reason() or "")


def test_a_real_load_average_is_a_percentage_of_capacity() -> None:
    from yazses.latency.load import cpu_percent

    value = cpu_percent()
    if value is None:
        pytest.skip("no load average on this platform")
    assert value >= 0.0


def test_the_decode_engine_falls_back_to_the_loaded_model(monkeypatch) -> None:
    """Every uncertainty resolves to "decode normally" — the failure mode here costs
    a slower decode, and the alternative costs the burst."""
    import yazses.latency.load as load
    from yazses.core.daemon import Daemon

    cfg = Config()
    cfg.latency.enabled = True
    fake = SimpleNamespace(_config=cfg, _engine="the-loaded-engine", _governor=None)

    assert Daemon._decode_engine(fake) == "the-loaded-engine"  # governor off

    class _Pool:
        def get(self, model, beam):
            return None                                   # not resident yet

    fake._governor = _Pool()
    assert Daemon._decode_engine(fake) == "the-loaded-engine"

    class _Boom:
        def get(self, model, beam):
            raise RuntimeError("pool is broken")

    fake._governor = _Boom()
    assert Daemon._decode_engine(fake) == "the-loaded-engine"

    monkeypatch.setattr(load, "cpu_percent", lambda: None)
    fake._governor = _Pool()
    assert Daemon._decode_engine(fake) == "the-loaded-engine"


def test_the_decode_engine_uses_the_light_model_under_load(monkeypatch) -> None:
    """The other direction: without this the fallbacks above would mean "always"."""
    import yazses.latency.load as load
    from yazses.core.daemon import Daemon
    from yazses.latency.governor import LIGHT_BEAM

    cfg = Config()
    cfg.latency.enabled = True
    asked: list[tuple[str, int]] = []

    class _Pool:
        def get(self, model, beam):
            asked.append((model, beam))
            return f"engine:{model}"

    monkeypatch.setattr(load, "cpu_percent", lambda: 99.0)
    fake = SimpleNamespace(_config=cfg, _engine="the-loaded-engine", _governor=_Pool())
    assert Daemon._decode_engine(fake) == "engine:tiny.en"
    assert asked == [("tiny.en", LIGHT_BEAM)]


def test_the_base_policy_asks_the_pool_for_the_configured_beam(monkeypatch) -> None:
    """At normal load the governor must ask for the width the user configured.

    It asked for a hardcoded 5. `EnginePool` is keyed on `(model, beam_size)` and
    is handed the daemon's own engine under `(stt.model, stt.beam_size)`, so a
    request for a different width missed that key every burst and loaded a second
    copy of the same model in the background -- while also discarding whatever the
    user had set `[stt] beam_size` to.
    """
    import yazses.latency.load as load
    from yazses.core.daemon import Daemon

    for configured in (0, 2, 8):
        cfg = Config()
        cfg.latency.enabled = True
        cfg.stt.beam_size = configured
        asked: list[tuple[str, int]] = []

        class _Pool:
            def get(self, model, beam):
                asked.append((model, beam))
                return f"engine:{model}"

        monkeypatch.setattr(load, "cpu_percent", lambda: 50.0)
        fake = SimpleNamespace(_config=cfg, _engine="the-loaded-engine", _governor=_Pool())
        Daemon._decode_engine(fake)
        assert asked == [(cfg.stt.model, configured)], (
            f"with [stt] beam_size = {configured} the governor asked the pool for "
            f"{asked}, which is not the key the daemon's own engine answers to"
        )


def test_the_beam_width_reaches_the_decoder() -> None:
    """The governor's beam choice is only real if the engine passes it to Whisper."""
    from yazses.stt.faster_whisper import FasterWhisperEngine

    engine = FasterWhisperEngine.__new__(FasterWhisperEngine)
    engine._language = "en"
    engine._beam_size = 1
    assert engine._decode_kwargs(None) == {"language": "en", "beam_size": 1}

    engine._beam_size = 0
    assert engine._decode_kwargs(None) == {"language": "en"}, (
        "beam_size = 0 must stay silent rather than pinning faster-whisper's default"
    )
