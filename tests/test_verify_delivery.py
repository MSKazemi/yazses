"""`verify --type` must report what ARRIVED, not that the sender did not complain."""
from __future__ import annotations

from yazses.system.typing_canary import (
    DELIVERED,
    INCONCLUSIVE,
    NOT_DELIVERED,
    Delivery,
)
from yazses.system.verify import verify


def _ok(**over):
    kw = dict(record=lambda: "a", level_of=lambda a: 0.01, threshold=0.004,
              transcribe=lambda a: "hello world")
    kw.update(over)
    return kw


def test_delivery_replaces_the_unobserved_injection_step():
    result = verify(**_ok(), deliver=lambda t: Delivery(DELIVERED, "arrived", t))
    assert result.ok
    assert [s.name for s in result.steps][-1] == "Delivery"
    assert "Injection" not in [s.name for s in result.steps]


def test_the_cleaned_transcript_is_what_gets_delivered():
    seen: list[str] = []
    verify(**_ok(), deliver=lambda t: seen.append(t) or Delivery(DELIVERED, "ok"))
    assert seen == ["hello world"]


def test_not_delivered_fails_the_chain_and_names_delivery():
    result = verify(**_ok(), deliver=lambda t: Delivery(NOT_DELIVERED, "nothing arrived"))
    assert not result.ok and result.failure is not None
    assert result.failure.name == "Delivery"


def test_inconclusive_is_a_failure_not_a_pass():
    result = verify(**_ok(), deliver=lambda t: Delivery(INCONCLUSIVE, "probe had no focus"))
    assert not result.ok
    assert result.failure is not None and "not proven" in result.failure.detail


def test_without_deliver_the_old_injection_behaviour_is_unchanged():
    typed: list[str] = []
    result = verify(**_ok(), inject=typed.append)
    assert result.ok and typed == ["hello world"]
    assert [s.name for s in result.steps][-1] == "Injection"
