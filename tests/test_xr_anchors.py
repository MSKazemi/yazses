"""Tests for yazses.xr.anchors — the XR panel registry, dictation pin and spoken label."""
from __future__ import annotations

import unicodedata

import pytest
from hypothesis import given
from hypothesis import strategies as st

from yazses.xr.anchors import DictationTarget, PanelRegistry, describe, describe_all
from yazses.xr.types import Panel, Vec3


def make_panel(pid: str, width: float = 0.4, label: str = "", z: float = -1.0,
               height: float = 0.3) -> Panel:
    return Panel(pid, Vec3(0, 0, z), Vec3(0, 0, 1), Vec3(0, 1, 0), width, height, label)


def test_upsert_get_and_stable_order() -> None:
    reg = PanelRegistry()
    for pid in ("c", "a", "b"):
        reg.upsert(make_panel(pid), 0.0)
    assert [p.panel_id for p in reg.panels()] == ["a", "b", "c"]
    assert reg.get("b") is not None and reg.get("zzz") is None
    assert len(reg) == 3


def test_upsert_existing_id_replaces_and_refreshes() -> None:
    reg = PanelRegistry(stale_after_s=10.0)
    reg.upsert(make_panel("a", label="old"), 0.0)
    reg.upsert(make_panel("a", label="new"), 8.0)
    assert len(reg) == 1 and reg.get("a").label == "new"
    assert reg.expire(17.0) == []  # 9 s since refresh, not 17
    assert reg.expire(18.0) == ["a"]  # exactly stale_after_s since refresh


def test_eviction_drops_least_recently_seen() -> None:
    reg = PanelRegistry(max_panels=3)
    reg.upsert(make_panel("a"), 1.0)
    reg.upsert(make_panel("b"), 2.0)
    reg.upsert(make_panel("c"), 3.0)
    reg.upsert(make_panel("a"), 4.0)  # refresh: b is now the oldest
    reg.upsert(make_panel("d"), 5.0)
    assert [p.panel_id for p in reg.panels()] == ["a", "c", "d"]


def test_refresh_at_capacity_does_not_evict() -> None:
    reg = PanelRegistry(max_panels=2)
    reg.upsert(make_panel("a"), 1.0)
    reg.upsert(make_panel("b"), 2.0)
    reg.upsert(make_panel("a"), 3.0)
    assert len(reg) == 2 and reg.get("b") is not None


def test_eviction_tie_is_deterministic_by_id() -> None:
    reg = PanelRegistry(max_panels=2)
    reg.upsert(make_panel("b"), 1.0)
    reg.upsert(make_panel("a"), 1.0)
    reg.upsert(make_panel("c"), 1.0)
    assert [p.panel_id for p in reg.panels()] == ["b", "c"]


def test_capacity_of_one() -> None:
    reg = PanelRegistry(max_panels=1)
    reg.upsert(make_panel("a"), 0.0)
    reg.upsert(make_panel("b"), 1.0)
    assert [p.panel_id for p in reg.panels()] == ["b"]


def test_expiry_boundary_is_half_open() -> None:
    reg = PanelRegistry(stale_after_s=30.0)
    reg.upsert(make_panel("a"), 100.0)
    assert reg.expire(129.999) == []
    assert reg.get("a") is not None
    assert reg.expire(130.0) == ["a"]
    assert reg.get("a") is None


def test_expire_returns_sorted_ids_and_keeps_fresh() -> None:
    reg = PanelRegistry(stale_after_s=5.0)
    reg.upsert(make_panel("z"), 0.0)
    reg.upsert(make_panel("m"), 0.0)
    reg.upsert(make_panel("keep"), 4.0)
    assert reg.expire(6.0) == ["m", "z"]
    assert [p.panel_id for p in reg.panels()] == ["keep"]


def test_clock_stepping_backwards_does_not_expire() -> None:
    reg = PanelRegistry(stale_after_s=5.0)
    reg.upsert(make_panel("a"), 100.0)
    assert reg.expire(50.0) == []
    assert reg.is_fresh("a", 50.0)


def test_remove() -> None:
    reg = PanelRegistry()
    reg.upsert(make_panel("a"), 0.0)
    assert reg.remove("a") is True
    assert reg.remove("a") is False
    assert reg.panels() == ()


@pytest.mark.parametrize("kwargs", [{"max_panels": 0}, {"max_panels": -1}, {"max_panels": True},
                                    {"max_panels": 1.5}, {"stale_after_s": 0.0},
                                    {"stale_after_s": -1.0}, {"stale_after_s": float("nan")},
                                    {"stale_after_s": float("inf")}])
def test_bad_registry_config_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        PanelRegistry(**kwargs)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True])
def test_bad_time_rejected(bad: float) -> None:
    reg = PanelRegistry()
    with pytest.raises(ValueError):
        reg.upsert(make_panel("a"), bad)
    with pytest.raises(ValueError):
        reg.expire(bad)


# --- DictationTarget -------------------------------------------------------------------

def test_pin_current_unpin() -> None:
    reg = PanelRegistry()
    reg.upsert(make_panel("a"), 0.0)
    tgt = DictationTarget(reg)
    assert tgt.current(0.0) is None
    tgt.pin("a", 0.0)
    assert tgt.current(1.0) == "a"
    tgt.unpin()
    assert tgt.current(1.0) is None


def test_pin_expires_at_ttl_boundary() -> None:
    reg = PanelRegistry(stale_after_s=1000.0)
    reg.upsert(make_panel("a"), 0.0)
    tgt = DictationTarget(reg)
    tgt.pin("a", 10.0, ttl_s=5.0)
    assert tgt.current(14.999) == "a"
    assert tgt.current(15.0) is None
    assert tgt.current(12.0) is None  # lapse is permanent, not re-armed by an earlier time


def test_default_ttl_is_sixty_seconds() -> None:
    reg = PanelRegistry(stale_after_s=1000.0)
    reg.upsert(make_panel("a"), 0.0)
    tgt = DictationTarget(reg)
    tgt.pin("a", 0.0)
    assert tgt.current(59.9) == "a"
    assert tgt.current(60.0) is None


def test_pin_on_missing_panel_raises_keyerror_and_keeps_old_pin() -> None:
    reg = PanelRegistry()
    reg.upsert(make_panel("a"), 0.0)
    tgt = DictationTarget(reg)
    tgt.pin("a", 0.0)
    with pytest.raises(KeyError):
        tgt.pin("ghost", 1.0)
    assert tgt.current(1.0) == "a"


def test_pin_on_stale_panel_raises_keyerror() -> None:
    reg = PanelRegistry(stale_after_s=5.0)
    reg.upsert(make_panel("a"), 0.0)
    with pytest.raises(KeyError):
        DictationTarget(reg).pin("a", 5.0)


def test_pinned_panel_removed_gives_none_and_stays_none() -> None:
    reg = PanelRegistry()
    reg.upsert(make_panel("a"), 0.0)
    tgt = DictationTarget(reg)
    tgt.pin("a", 0.0)
    reg.remove("a")
    assert tgt.current(1.0) is None
    reg.upsert(make_panel("a"), 2.0)  # same id reappearing must not resurrect the old pin
    assert tgt.current(3.0) is None


def test_pinned_panel_expired_gives_none() -> None:
    reg = PanelRegistry(stale_after_s=10.0)
    reg.upsert(make_panel("a"), 0.0)
    tgt = DictationTarget(reg)
    tgt.pin("a", 0.0, ttl_s=100.0)
    reg.expire(10.0)
    assert tgt.current(10.0) is None


def test_pinned_panel_stale_but_not_yet_expired_gives_none() -> None:
    reg = PanelRegistry(stale_after_s=10.0)
    reg.upsert(make_panel("a"), 0.0)
    tgt = DictationTarget(reg)
    tgt.pin("a", 0.0, ttl_s=100.0)
    assert tgt.current(10.0) is None


def test_pinned_panel_evicted_gives_none() -> None:
    reg = PanelRegistry(max_panels=1)
    reg.upsert(make_panel("a"), 0.0)
    tgt = DictationTarget(reg)
    tgt.pin("a", 0.0)
    reg.upsert(make_panel("b"), 1.0)
    assert tgt.current(1.0) is None


def test_refreshing_pinned_panel_keeps_it_alive() -> None:
    reg = PanelRegistry(stale_after_s=10.0)
    reg.upsert(make_panel("a"), 0.0)
    tgt = DictationTarget(reg)
    tgt.pin("a", 0.0, ttl_s=100.0)
    reg.upsert(make_panel("a"), 9.0)
    assert tgt.current(15.0) == "a"


@pytest.mark.parametrize("ttl", [0.0, -1.0, float("nan"), float("inf")])
def test_bad_ttl_rejected(ttl: float) -> None:
    reg = PanelRegistry()
    reg.upsert(make_panel("a"), 0.0)
    with pytest.raises(ValueError):
        DictationTarget(reg).pin("a", 0.0, ttl_s=ttl)


# --- describe --------------------------------------------------------------------------

def test_describe_basic() -> None:
    assert describe(make_panel("a", 0.4, "Notes")) == 'Panel labelled "Notes", 40 centimetres wide'


def test_describe_unlabelled_and_singular() -> None:
    assert describe(make_panel("a", 0.4)) == "Unlabelled panel, 40 centimetres wide"
    assert describe(make_panel("a", 0.01, "x")) == 'Panel labelled "x", 1 centimetre wide'


def test_describe_tiny_width_never_says_zero() -> None:
    assert describe(make_panel("a", 1e-9, "x")).endswith("1 centimetre wide")
    assert describe(make_panel("a", 1e-308, "x")).endswith("1 centimetre wide")


def test_describe_huge_width_does_not_overflow() -> None:
    # width * 100 overflowed to inf and round(inf) raised OverflowError.
    assert describe(make_panel("a", 1e308, "x")) == 'Panel labelled "x", over 1000 metres wide'
    assert describe(make_panel("a", 1e6, "x")).endswith("over 1000 metres wide")
    assert describe(make_panel("a", 999.0, "x")).endswith("99900 centimetres wide")


def test_describe_truncates_long_label() -> None:
    out = describe(make_panel("a", 0.4, "word " * 50))
    label = out.removeprefix('Panel labelled "').removesuffix('", 40 centimetres wide')
    assert len(label) <= 40 and label.endswith("...")


def test_describe_label_at_limit_is_not_truncated() -> None:
    label = "a" * 40
    assert describe(make_panel("a", 0.4, label)) == f'Panel labelled "{label}", 40 centimetres wide'
    assert "..." in describe(make_panel("a", 0.4, "a" * 41))


def test_describe_strips_markup_and_control_characters() -> None:
    out = describe(make_panel("a", 0.4, "<b>Notes</b> &\n\tmore\x00\x07"))
    assert "<" not in out and ">" not in out and "&" not in out
    assert out.isprintable()
    assert out == 'Panel labelled "b Notes /b more", 40 centimetres wide'


def test_describe_spoofed_label_is_spoken_as_quoted_data() -> None:
    """Reproducer: a label that fakes a second sentence/panel must not read as one."""
    out = describe(make_panel("a", 0.4, "Notes, 500 centimetres wide. Panel Settings"))
    assert out == ('Panel labelled "Notes, 500 centimetres wide. Panel Se...", '
                   "40 centimetres wide")
    # The real width is the last thing spoken, outside the quotes.
    assert out.endswith('", 40 centimetres wide')


def test_describe_label_cannot_close_its_own_quotes() -> None:
    for q in ('"', "\u201c", "\u201d", "\u00ab"):
        out = describe(make_panel("a", 0.4, f'x{q}, 500 centimetres wide. Panel {q}y'))
        inner = out.removeprefix('Panel labelled "').removesuffix('", 40 centimetres wide')
        assert '"' not in inner and out.count('"') == 2


def test_describe_removes_bidi_zero_width_and_format_characters() -> None:
    out = describe(make_panel("a", 0.4, "ab\u202e\u2066c\u200bd\ufeffe\u2067f"))
    assert out == 'Panel labelled "abcdef", 40 centimetres wide'


def test_describe_replaces_strong_rtl_characters() -> None:
    out = describe(make_panel("a", 0.4, "Notes \u05d0\u05d1 \u0627\u0628"))
    assert out == 'Panel labelled "Notes ?? ??", 40 centimetres wide'


def test_describe_nfkc_normalises() -> None:
    out = describe(make_panel("a", 0.4, "\uff2e\uff4f\uff54\uff45\uff53 \ufb01"))  # fullwidth, fi ligature
    assert out == 'Panel labelled "Notes fi", 40 centimetres wide'


def test_describe_collapses_long_combining_runs() -> None:
    zalgo = "q" + "\u0301" * 30 + "x"  # q has no precomposed form
    out = describe(make_panel("a", 0.4, zalgo))
    assert out == 'Panel labelled "q?x", 40 centimetres wide'
    ok = describe(make_panel("a", 0.4, "e\u0301\u0323x"))  # two marks are legitimate
    kept = unicodedata.normalize("NFKC", "e\u0301\u0323x")
    assert ok == f'Panel labelled "{kept}", 40 centimetres wide' and "?" not in ok
    # zero-width joiners cannot split a run to dodge the limit
    split = describe(make_panel("a", 0.4, "q" + "\u0301\u200d" * 10 + "x"))
    assert "?" in split and split.count("\u0301") <= 2


def test_describe_all_disambiguates_shared_labels() -> None:
    a = make_panel("b", label="Notes")
    b = make_panel("a", label="Notes")
    c = make_panel("c", label="Other")
    d = make_panel("d")
    e = make_panel("e")
    out = describe_all([a, b, c, d, e])
    assert out == (
        'Panel labelled "Notes", second of 2, 40 centimetres wide',   # id "b"
        'Panel labelled "Notes", first of 2, 40 centimetres wide',    # id "a"
        'Panel labelled "Other", 40 centimetres wide',
        "Unlabelled panel, first of 2, 40 centimetres wide",
        "Unlabelled panel, second of 2, 40 centimetres wide",
    )
    assert describe_all([]) == ()
    assert describe_all([c]) == (describe(c),)


def test_describe_all_groups_by_spoken_label_and_handles_many() -> None:
    ps = [make_panel(f"p{i:02d}", label="Notes" if i % 2 else "Notes\u200b") for i in range(12)]
    out = describe_all(ps)
    assert len(set(out)) == 12  # all distinguishable
    assert "number 11 of 12" in " ".join(out) and "tenth of 12" in " ".join(out)


@given(st.text(max_size=256), st.floats(min_value=1e-6, max_value=1e4))
def test_describe_is_always_plain_printable(label: str, width: float) -> None:
    out = describe(make_panel("p", width, label))
    assert out.isprintable() and "<" not in out and ">" not in out and "&" not in out
    assert out.endswith(" wide") and len(out) <= 120
    inner = out.removeprefix('Panel labelled "')
    if out.startswith("Panel labelled"):
        assert out.count('"') == 2
        spoken = inner.rsplit('", ', 1)[0]
        assert not any(unicodedata.bidirectional(ch) in ("R", "AL") for ch in spoken)
        assert not any(unicodedata.category(ch)[0] == "C" for ch in spoken)


@given(st.floats(min_value=1e-320, max_value=1.7e308))
def test_describe_never_raises_for_any_finite_width(width: float) -> None:
    assert describe(make_panel("p", width, "x")).endswith(" wide")


# --- panel ids -------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["caf\u00e9", "cafe\u0301", "p\u0430", " ", "", "\t", "a b",
                                 "a/b", "x" * 129, "\uff50\uff11", "p1\u200b"])
def test_upsert_rejects_non_canonical_ids(bad: str) -> None:
    reg = PanelRegistry()
    try:
        panel = make_panel(bad)
    except ValueError:
        return  # Panel itself refused (empty / over-long / unprintable)
    with pytest.raises(ValueError):
        reg.upsert(panel, 0.0)
    assert len(reg) == 0


def test_nfc_and_nfd_ids_never_become_two_entries() -> None:
    reg = PanelRegistry()
    for pid in ("caf\u00e9", unicodedata.normalize("NFD", "caf\u00e9")):
        with pytest.raises(ValueError):
            reg.upsert(make_panel(pid), 0.0)
    assert len(reg) == 0


def test_padded_id_is_stripped_and_aliases_the_canonical_one() -> None:
    reg = PanelRegistry()
    reg.upsert(make_panel(" p1"), 0.0)
    reg.upsert(make_panel("p1 "), 1.0)
    assert len(reg) == 1 and [p.panel_id for p in reg.panels()] == ["p1"]
    assert reg.get(" p1 ") is not None and reg.is_fresh("p1\n", 1.0)
    assert reg.remove(" p1") is True and len(reg) == 0


def test_lookups_with_invalid_ids_find_nothing() -> None:
    reg = PanelRegistry()
    reg.upsert(make_panel("p1"), 0.0)
    assert reg.get("p\u0430") is None and reg.get("") is None
    assert reg.get(None) is None  # type: ignore[arg-type]
    assert reg.remove("p\u0430") is False and not reg.is_fresh("p\u0430", 0.0)
    with pytest.raises(KeyError):
        DictationTarget(reg).pin("p\u0430", 0.0)
    with pytest.raises(KeyError):
        DictationTarget(reg).pin(" ", 0.0)


def test_pin_accepts_padded_id() -> None:
    reg = PanelRegistry()
    reg.upsert(make_panel("p1"), 0.0)
    tgt = DictationTarget(reg)
    tgt.pin(" p1 ", 0.0)
    assert tgt.current(1.0) == "p1"


# --- last_seen is monotonic -------------------------------------------------------------

def test_older_now_s_does_not_rewind_last_seen() -> None:
    reg = PanelRegistry(stale_after_s=10.0)
    reg.upsert(make_panel("a"), 100.0)
    reg.upsert(make_panel("a", label="late report"), 5.0)  # reordered / replayed
    assert reg.get("a").label == "late report"  # content still replaced
    assert reg.is_fresh("a", 105.0)   # would be stale (100 s old vs 5) if rewound
    assert reg.expire(105.0) == []
    assert reg.expire(110.0) == ["a"]


def test_eviction_uses_monotonic_last_seen() -> None:
    reg = PanelRegistry(max_panels=2)
    reg.upsert(make_panel("a"), 10.0)
    reg.upsert(make_panel("b"), 5.0)
    reg.upsert(make_panel("a"), 1.0)  # must not make "a" the oldest
    reg.upsert(make_panel("c"), 11.0)
    assert [p.panel_id for p in reg.panels()] == ["a", "c"]


# --- pin geometry fingerprint -----------------------------------------------------------

def _pinned(**kw: float) -> tuple[PanelRegistry, DictationTarget]:
    reg = PanelRegistry(stale_after_s=1000.0)
    reg.upsert(make_panel("a"), 0.0)
    tgt = DictationTarget(reg, **kw)
    tgt.pin("a", 0.0, ttl_s=1000.0)
    return reg, tgt


def test_pin_survives_small_move_and_resize() -> None:
    reg, tgt = _pinned()
    reg.upsert(make_panel("a", z=-1.3, width=0.45, height=0.33), 1.0)  # 0.3 m, +12 %, +10 %
    assert tgt.current(2.0) == "a"


def test_pin_dropped_when_centre_moves_beyond_tolerance() -> None:
    reg, tgt = _pinned()
    reg.upsert(make_panel("a", z=-1.6), 1.0)  # 0.6 m > 0.5 m default
    assert tgt.current(2.0) is None
    reg.upsert(make_panel("a"), 3.0)  # moving back does not resurrect the dropped pin
    assert tgt.current(4.0) is None


def test_pin_move_tolerance_is_configurable_and_inclusive_boundary() -> None:
    reg, tgt = _pinned(pin_move_tolerance_m=0.1)
    reg.upsert(make_panel("a", z=-1.2), 1.0)
    assert tgt.current(2.0) is None
    reg2, tgt2 = _pinned(pin_move_tolerance_m=2.0)
    reg2.upsert(make_panel("a", z=-2.5), 1.0)
    assert tgt2.current(2.0) == "a"


def test_pin_dropped_when_size_changes_more_than_twenty_percent() -> None:
    for kw in ({"width": 0.49}, {"width": 0.31}, {"height": 0.37}, {"height": 0.23}):
        reg, tgt = _pinned()
        reg.upsert(make_panel("a", **kw), 1.0)
        assert tgt.current(2.0) is None, kw
    reg, tgt = _pinned()
    reg.upsert(make_panel("a", width=0.47, height=0.25), 1.0)  # +17.5 %, -16.7 %
    assert tgt.current(2.0) == "a"


def test_pin_dropped_when_panel_is_turned_around() -> None:
    reg, tgt = _pinned()
    flipped = Panel("a", Vec3(0, 0, -1), Vec3(0, 0, -1), Vec3(0, 1, 0), 0.4, 0.3)
    reg.upsert(flipped, 1.0)
    assert tgt.current(2.0) is None


def test_slow_creep_is_measured_against_the_pose_at_pin_time() -> None:
    reg, tgt = _pinned()
    for i in range(1, 8):  # 0.1 m per step: each step is small, the total is not
        reg.upsert(make_panel("a", z=-1.0 - 0.1 * i), float(i))
    assert tgt.current(8.0) is None


def test_repin_takes_a_new_fingerprint() -> None:
    reg, tgt = _pinned()
    reg.upsert(make_panel("a", z=-1.6), 1.0)
    tgt.pin("a", 2.0)  # the user re-chose the panel where it is now
    assert tgt.current(3.0) == "a"


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_bad_pin_tolerance_rejected(bad: float) -> None:
    with pytest.raises(ValueError):
        DictationTarget(PanelRegistry(), pin_move_tolerance_m=bad)
    with pytest.raises(ValueError):
        DictationTarget(PanelRegistry(), pin_turn_tolerance_rad=bad)


# --- Hypothesis: boundedness -----------------------------------------------------------

_IDS = st.sampled_from([f"p{i}" for i in range(12)])
_OPS = st.one_of(
    st.tuples(st.just("upsert"), _IDS, st.floats(0, 1000)),
    st.tuples(st.just("remove"), _IDS, st.just(0.0)),
    st.tuples(st.just("expire"), _IDS, st.floats(0, 1000)),
)


@given(st.integers(1, 6), st.lists(_OPS, max_size=80))
def test_registry_never_exceeds_max_panels(max_panels: int, ops: list) -> None:
    reg = PanelRegistry(max_panels=max_panels, stale_after_s=50.0)
    for op, pid, t in ops:
        if op == "upsert":
            reg.upsert(make_panel(pid), t)
        elif op == "remove":
            reg.remove(pid)
        else:
            reg.expire(t)
        assert len(reg) <= max_panels
        ids = [p.panel_id for p in reg.panels()]
        assert ids == sorted(ids) and len(set(ids)) == len(ids)


@given(st.integers(1, 5), st.lists(_OPS, max_size=60), st.floats(0, 1000))
def test_pin_never_dangles(max_panels: int, ops: list, probe: float) -> None:
    reg = PanelRegistry(max_panels=max_panels, stale_after_s=50.0)
    tgt = DictationTarget(reg)
    reg.upsert(make_panel("p0"), 0.0)
    tgt.pin("p0", 0.0, ttl_s=500.0)
    for op, pid, t in ops:
        if op == "upsert":
            reg.upsert(make_panel(pid), t)
        elif op == "remove":
            reg.remove(pid)
        else:
            reg.expire(t)
        cur = tgt.current(probe)
        assert cur is None or reg.get(cur) is not None
