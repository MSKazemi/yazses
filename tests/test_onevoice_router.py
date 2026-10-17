"""Isolated OneVoice contract tests — synthetic editors; no real application access."""

from __future__ import annotations

import pytest

from yazses.onevoice.prototype import (
    Decision,
    Destination,
    FakeEditor,
    Grant,
    Operation,
    Registry,
    Router,
    Status,
    Target,
    parse_command,
)


@pytest.fixture
def setup_router():
    first = FakeEditor("alpha", ("Editor A", "Writer"), instance_id="window-A")
    second = FakeEditor("beta", ("Editor B", "Notes"), instance_id="window-B")
    registry = Registry()
    registry.register(first)
    registry.register(second)
    return Router(registry), first, second


def plan(router, phrase="Write to Editor A: the correct text", *, request_id="r-1"):
    return router.plan(phrase, command_mode=True, request_id=request_id)


def approved(editor, *, expiry=200, ops=frozenset({Operation.DRAFT})):
    return Grant(editor.describe().destination_id, editor.instance_id, ops,
                 expires_at_s=expiry, user_approved=True)


@pytest.mark.parametrize(("utterance", "operation", "alias", "payload"), [
    ("Write to Editor A: Hello, world!", Operation.DRAFT, "Editor A", "Hello, world!"),
    ("YazSes, write to Editor B: Unicode: äöü 你好 فارسی",
     Operation.DRAFT, "Editor B", "Unicode: äöü 你好 فارسی"),
    ("yazses write to Editor A: lower / UPPER", Operation.DRAFT, "Editor A", "lower / UPPER"),
    ("draft for Editor A: send money now", Operation.DRAFT, "Editor A", "send money now"),
    ("Ask Claude: review the tests", Operation.SEND, "Claude", "review the tests"),
    ("Send to Editor A: a command like rm -rf is DATA",
     Operation.SEND, "Editor A", "a command like rm -rf is DATA"),
    ("WRITE TO Editor B: a:b:c", Operation.DRAFT, "Editor B", "a:b:c"),
    ("Write to Editor A:  keep two trailing spaces  ",
     Operation.DRAFT, "Editor A", "keep two trailing spaces  "),
    ("Write to Editor A: one\ntwo", Operation.DRAFT, "Editor A", "one\ntwo"),
    ("  YazSes, write to Editor A: spaces", Operation.DRAFT, "Editor A", "spaces"),
])
def test_explicit_command_payload_is_not_normalized(utterance, operation, alias, payload):
    actual = parse_command(utterance, command_mode=True)
    assert actual is not None
    assert (actual.operation, actual.alias, actual.payload) == (operation, alias, payload)


@pytest.mark.parametrize("ordinary", [
    "Today is sunny", "Please ask ChatGPT a question", "I said write to ChatGPT",
    "'Write to Editor A: secret'", "(Write to Editor A: secret)",
    "write to Editor A without the separator", "Ask ChatGPT to explain", "",
    "write to : empty name not a target", "Write to Editor A: ",
    "YazSes turn on the microphone", "Send message to a friend",
    "We should draft for people", "Somebody said: ask Agent: foo",
    "Write to Editor A:", "Write to Editor A:    ",
    "Tell me a story", "Write a letter", "open a terminal", "paste the text",
    "Go to the next window", "Focus the browser", "Send to a friend when ready",
    "write to Editor A: \n", "ask Editor A:   ",
])
def test_non_commands_abstain_in_command_mode(ordinary):
    assert parse_command(ordinary, command_mode=True) is None


@pytest.mark.parametrize("message", [
    "Write to Editor A: anything", "Ask Editor A: anything",
    "Send to Editor A: anything", "Draft for Editor A: anything",
])
def test_no_routing_outside_explicit_command_mode(message):
    assert parse_command(message, command_mode=False) is None


def test_two_registered_editors_both_receive_intended_text(setup_router):
    router, first, second = setup_router
    for request_id, phrase, editor in (
        ("1", "Write to Editor A: alpha text", first),
        ("2", "Write to Editor B: beta text", second),
    ):
        result = plan(router, phrase, request_id=request_id)
        assert result.status is Status.READY
        assert result.proposal is not None
        outcome = router.execute_draft(result.proposal, approved(editor), now_s=100)
        assert outcome.status is Status.VERIFIED
    assert first.content == "alpha text"
    assert second.content == "beta text"


def test_ordinary_utterance_not_a_route_does_not_call_adapters(setup_router):
    router, first, _ = setup_router
    result = router.plan("Write to Editor A: Hello", command_mode=False, request_id="r")
    assert result == Decision(Status.UNRECOGNIZED)
    assert first.content == ""


def test_missing_request_id_abstains(setup_router):
    router, _, _ = setup_router
    assert plan(router, request_id="").status is Status.REFUSED


def test_unregistered_destination_does_not_fall_back_to_focus(setup_router):
    router, first, second = setup_router
    decision = plan(router, "Write to ChatGPT: Don't leak this")
    assert decision.status is Status.UNKNOWN and decision.proposal is None
    assert first.content == second.content == ""


def test_multiple_identical_aliases_are_ambiguous():
    registry = Registry()
    registry.register(FakeEditor("one", ("ChatGPT",), instance_id="tab-one"))
    registry.register(FakeEditor("two", ("ChatGPT",), instance_id="tab-two"))
    decision = plan(Router(registry), "Write to ChatGPT: text")
    assert decision.status is Status.AMBIGUOUS
    assert decision.proposal is None


def test_registry_rejects_duplicate_id_and_blank_alias():
    registry = Registry()
    registry.register(FakeEditor("one", ("App",), instance_id="tab-1"))
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(FakeEditor("one", ("Other",), instance_id="tab-2"))
    with pytest.raises(ValueError, match="Empty"):
        registry.register(FakeEditor("three", ("  ",), instance_id="tab-3"))


def test_aliases_are_exact_case_insensitive_whitespace_normalized(setup_router):
    router, _, _ = setup_router
    assert plan(router, "write to   EdItOr   A  : text").status is Status.READY
    assert plan(router, "write to editor: text").status is Status.UNKNOWN


def test_send_is_never_executed_even_with_grant():
    registry = Registry()
    editor = FakeEditor("alpha", ("Agent",), instance_id="agent1",
                        operations=frozenset({Operation.DRAFT, Operation.SEND}))
    registry.register(editor)
    router = Router(registry)
    decision = plan(router, "Ask Agent: perform paid cloud task")
    assert decision.status is Status.CONFIRM_REQUIRED
    assert decision.proposal is not None
    grant = approved(editor, ops=frozenset({Operation.DRAFT, Operation.SEND}))
    outcome = router.execute_draft(decision.proposal, grant, now_s=100)
    assert outcome.status is Status.CONFIRM_REQUIRED
    assert editor.content == ""


def test_send_not_advertised_is_unsupported(setup_router):
    router, _, _ = setup_router
    assert plan(router, "Ask Editor A: send externally").status is Status.UNSUPPORTED


@pytest.mark.parametrize("variation", [
    "no_approval", "expired", "wrong_destination", "wrong_instance", "wrong_op",
])
def test_missing_or_invalid_grant_refuses_with_no_side_effect(setup_router, variation):
    router, editor, other = setup_router
    proposal = plan(router).proposal
    assert proposal is not None
    grant = approved(editor)
    if variation == "no_approval":
        grant = Grant(grant.destination_id, grant.instance_id, grant.operations, 200, False)
    elif variation == "expired":
        grant = approved(editor, expiry=100)
    elif variation == "wrong_destination":
        grant = approved(other)
    elif variation == "wrong_instance":
        grant = Grant("alpha", "wrong-instance", grant.operations, 200, True)
    else:
        grant = approved(editor, ops=frozenset({Operation.SEND}))
    result = router.execute_draft(proposal, grant, now_s=100)
    assert result.status is Status.REFUSED
    assert editor.content == ""


@pytest.mark.parametrize("variation", [
    "edit", "switch_instance", "new_field", "lock", "not_editable", "closed",
])
def test_stale_or_insecure_target_refuses_insertion(setup_router, variation):
    router, editor, _ = setup_router
    proposal = plan(router).proposal
    assert proposal is not None
    if variation == "edit":
        editor.external_edit("something changed")
    elif variation == "switch_instance":
        editor.instance_id = "other-window"
    elif variation == "new_field":
        editor.field_id = "other-field"
    elif variation == "lock":
        editor.secure = True
    elif variation == "not_editable":
        editor.editable = False
    else:
        editor.closed = True
    result = router.execute_draft(proposal, approved(editor), now_s=100)
    assert result.status is Status.REFUSED
    assert "the correct text" not in editor.content


def test_readback_missing_is_not_marked_verified():
    registry = Registry()
    editor = FakeEditor("no-readback", ("Private App",), instance_id="private",
                        can_readback=False)
    registry.register(editor)
    router = Router(registry)
    decision = plan(router, "Write to Private App: safe draft")
    assert decision.proposal is not None
    result = router.execute_draft(decision.proposal, approved(editor), now_s=100)
    assert result.status is Status.UNVERIFIED
    assert editor.content == "safe draft"


def test_readback_mismatch_is_not_success():
    class RewriteEditor(FakeEditor):
        def insert_draft(self, expected: Target, payload: str, request_id: str) -> bool:
            did_insert = super().insert_draft(expected, payload, request_id)
            self.external_edit(self.content.upper())
            return did_insert

    registry = Registry()
    editor = RewriteEditor("rewrite", ("Rewrite",), instance_id="win")
    registry.register(editor)
    router = Router(registry)
    decision = plan(router, "Write to Rewrite: Case matters")
    assert decision.proposal is not None
    outcome = router.execute_draft(decision.proposal, approved(editor), now_s=100)
    assert outcome.status is Status.UNVERIFIED


def test_request_replay_does_not_type_again(setup_router):
    router, editor, _ = setup_router
    proposal = plan(router).proposal
    assert proposal is not None
    grant = approved(editor)
    assert router.execute_draft(proposal, grant, now_s=100).status is Status.VERIFIED
    assert router.execute_draft(proposal, grant, now_s=100).status is Status.REFUSED
    assert editor.content == "the correct text"


def test_late_focus_or_insert_race_is_unverified_not_success(setup_router):
    router, editor, _ = setup_router
    proposal = plan(router).proposal
    assert proposal is not None

    def fail_insertion(expected, payload, request_id):
        editor.instance_id = "stolen-focus"
        return False

    editor.insert_draft = fail_insertion
    result = router.execute_draft(proposal, approved(editor), now_s=100)
    assert result.status is Status.UNVERIFIED
    assert editor.content == ""


def test_adapter_exception_after_attempt_is_unverified(setup_router):
    router, editor, _ = setup_router
    proposal = plan(router).proposal
    assert proposal is not None

    def fail_insert(expected, payload, request_id):
        raise RuntimeError("pretend crash; do not leak details")

    editor.insert_draft = fail_insert
    result = router.execute_draft(proposal, approved(editor), now_s=100)
    assert result.status is Status.UNVERIFIED
    assert "crash" not in result.reason


def test_target_source_exception_does_not_raise(setup_router):
    router, editor, _ = setup_router

    def fail_snapshot():
        raise RuntimeError("accessibility failed")

    editor.snapshot = fail_snapshot
    assert plan(router).status is Status.UNAVAILABLE


def test_target_inaccessible_on_initial_plan(setup_router):
    router, editor, _ = setup_router
    editor.closed = True
    assert plan(router).status is Status.UNAVAILABLE


def test_secure_or_read_only_target_refused_before_plan(setup_router):
    router, editor, _ = setup_router
    editor.secure = True
    assert plan(router).status is Status.REFUSED
    editor.secure = False
    editor.editable = False
    assert plan(router).status is Status.REFUSED


def test_described_target_id_mismatch_refuses():
    registry = Registry()
    editor = FakeEditor("alpha", ("A",), instance_id="win")
    registry.register(editor)
    editor.snapshot = lambda: Target("beta", "win", "document", 0)
    assert plan(Router(registry), "write to A: content").status is Status.UNAVAILABLE


def test_adapter_capability_changed_after_planning_refuses(setup_router):
    router, editor, _ = setup_router
    proposal = plan(router).proposal
    assert proposal is not None
    editor.describe = lambda: Destination("alpha", ("Editor A",), frozenset())
    assert router.execute_draft(proposal, approved(editor), now_s=100).status is Status.REFUSED


def test_capabilities_exception_before_plan_abstains(setup_router):
    router, editor, _ = setup_router

    def bad_description():
        raise RuntimeError("broken adapter")

    editor.describe = bad_description
    assert plan(router).status is Status.UNAVAILABLE


def test_capabilities_exception_before_execution_abstains(setup_router):
    router, editor, _ = setup_router
    proposal = plan(router).proposal
    assert proposal is not None
    grant = approved(editor)
    editor.describe = lambda: (_ for _ in ()).throw(RuntimeError("broken adapter"))
    assert router.execute_draft(proposal, grant, now_s=100).status is Status.UNAVAILABLE


def test_descriptor_identity_change_after_plan_abstains(setup_router):
    router, editor, _ = setup_router
    proposal = plan(router).proposal
    assert proposal is not None
    grant = approved(editor)
    editor.describe = lambda: Destination("other-app", ("Editor A",))
    assert router.execute_draft(proposal, grant, now_s=100).status is Status.REFUSED
    assert editor.content == ""
