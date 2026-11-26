"""`[injection] type_delay_ms`: configurable typing speed for xdotool, ydotool and wtype.

The default (-1) must leave every backend's argv byte-for-byte as it was before the key
existed; an explicit value must reach each backend's own pacing flag; and the loader must
refuse anything outside -1..200 with a warning and the default.
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yazses.config import InjectionConfig
from yazses.configcheck import build_section
from yazses.inject import pacing
from yazses.inject import ydotool as yd
from yazses.inject.auto import apply_injection_config
from yazses.inject.wtype import WtypeInjector
from yazses.inject.xdotool import XdotoolInjector


class _Run:
    def __init__(self):
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture
def run(monkeypatch):
    recorder = _Run()
    monkeypatch.setattr(subprocess, "run", recorder)
    return recorder


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv(pacing.ENV_VAR, "")  # recorded, so teardown restores it
    monkeypatch.delenv(pacing.ENV_VAR)
    yd.set_ydotool_dialect(None)
    yield
    yd.set_ydotool_dialect(None)


def _set(monkeypatch, ms: int) -> None:
    monkeypatch.setenv(pacing.ENV_VAR, str(ms))


# --- the default is today's behaviour -----------------------------------------


def test_the_default_is_backend_default():
    assert InjectionConfig().type_delay_ms == -1
    assert pacing.type_delay_ms() is None


def test_xdotool_default_argv_is_unchanged(run):
    XdotoolInjector().inject("hello")
    argv, kwargs = run.calls[0]
    assert argv == ["xdotool", "type", "--clearmodifiers", "--delay", "12", "--", "hello"]
    assert kwargs["timeout"] == pytest.approx(10.0 + 5 * 0.03)


def test_wtype_default_argv_is_unchanged(run):
    WtypeInjector().inject("hello")
    argv, kwargs = run.calls[0]
    assert argv == ["wtype", "--", "hello"]
    assert kwargs["timeout"] == 10


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        (yd.DIALECT_V1, ["ydotool", "type", "-d", "6", "-H", "6", "--", "hi"]),
        (yd.DIALECT_V0, ["ydotool", "type", "--key-delay", "6", "--", "hi"]),
    ],
)
def test_ydotool_default_argv_is_unchanged(dialect, expected):
    assert yd.YdotoolInjector()._type_argv("hi", dialect) == expected


# --- a configured value reaches each backend ----------------------------------


@pytest.mark.parametrize("ms", [0, 5, 12, 200])
def test_xdotool_uses_delay(run, monkeypatch, ms):
    _set(monkeypatch, ms)
    XdotoolInjector().inject("hello")
    argv, _ = run.calls[0]
    assert argv == ["xdotool", "type", "--clearmodifiers", "--delay", str(ms), "--", "hello"]


def test_xdotool_key_pacing_is_not_touched(run, monkeypatch):
    _set(monkeypatch, 0)
    XdotoolInjector().inject_backspaces(3)
    assert "--delay" not in run.calls[0][0]


def test_wtype_uses_dash_d_before_the_text(run, monkeypatch):
    _set(monkeypatch, 5)
    WtypeInjector().inject("hello")
    argv, _ = run.calls[0]
    assert argv == ["wtype", "-d", "5", "--", "hello"]


def test_wtype_zero_sends_no_dash_d(run, monkeypatch):
    # Upstream main.c refuses `-d 0` ("Invalid sleep time"); its default is already 0.
    _set(monkeypatch, 0)
    WtypeInjector().inject("hello")
    assert run.calls[0][0] == ["wtype", "--", "hello"]


@pytest.mark.parametrize(
    ("ms", "v1", "v0"),
    [
        (0, ("0", "0"), "0"),
        (5, ("3", "2"), "3"),
        (12, ("6", "6"), "6"),
        (200, ("100", "100"), "100"),
    ],
)
def test_ydotool_splits_the_budget(monkeypatch, ms, v1, v0):
    _set(monkeypatch, ms)
    inj = yd.YdotoolInjector()
    assert inj._type_argv("hi", yd.DIALECT_V1) == [
        "ydotool", "type", "-d", v1[0], "-H", v1[1], "--", "hi",
    ]
    assert inj._type_argv("hi", yd.DIALECT_V0) == [
        "ydotool", "type", "--key-delay", v0, "--", "hi",
    ]


def test_ydotool_inject_sends_configured_pacing(run, monkeypatch):
    _set(monkeypatch, 4)
    yd.set_ydotool_dialect(yd.DIALECT_V1)
    yd.YdotoolInjector().inject("ab")
    assert run.calls[0][0] == ["ydotool", "type", "-d", "2", "-H", "2", "--", "ab"]


def test_a_slow_delay_scales_the_timeout(run, monkeypatch):
    # A timeout mid-string makes LinuxInjector paste the whole text a second time.
    _set(monkeypatch, 200)
    text = "x" * 1000
    XdotoolInjector().inject(text)
    WtypeInjector().inject(text)
    for _, kwargs in run.calls:
        assert kwargs["timeout"] >= 1000 * 0.2 * 2


# --- validation ---------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "-1", "201", "-7", "abc", "4.5", None, True])
def test_parse_rejects_to_backend_default(raw):
    assert pacing.parse_type_delay(raw) is None


@pytest.mark.parametrize("raw", ["0", "6", "200", 4])
def test_parse_accepts_the_range(raw):
    assert pacing.parse_type_delay(raw) == int(raw)


@pytest.mark.parametrize("value", [0, 4, 200, -1])
def test_configcheck_accepts_in_range(value):
    problems: list = []
    cfg = build_section(InjectionConfig, {"type_delay_ms": value}, "injection", problems)
    assert cfg.type_delay_ms == value
    assert problems == []


@pytest.mark.parametrize("value", [201, 1000, -2, "fast", True])
def test_configcheck_warns_and_falls_back(value):
    problems: list = []
    cfg = build_section(InjectionConfig, {"type_delay_ms": value}, "injection", problems)
    assert cfg.type_delay_ms == -1
    assert len(problems) == 1
    assert problems[0].key == "type_delay_ms"
    assert not problems[0].repaired


# --- the bridge ---------------------------------------------------------------


def test_apply_injection_config_bridges_and_clears(monkeypatch):
    import os

    # The bridge also writes these; record them so teardown restores them.
    for name in ("YAZSES_INJECTOR", "YAZSES_INJECT_FALLBACK", "YAZSES_PORTAL_CONSENT"):
        monkeypatch.setenv(name, os.environ.get(name, ""))
        if not os.environ[name]:
            monkeypatch.delenv(name)
    apply_injection_config(InjectionConfig(type_delay_ms=5))
    assert os.environ[pacing.ENV_VAR] == "5"
    assert pacing.type_delay_ms() == 5
    apply_injection_config(InjectionConfig())
    assert pacing.ENV_VAR not in os.environ
