"""A safe two-app demonstration using in-memory editors only.

Run with: PYTHONPATH=src python -m yazses.onevoice.demo
No audio, desktop window control, network, login or external agents are involved.
"""

from .prototype import FakeEditor, Grant, Operation, Registry, Router


def main() -> None:
    registry = Registry()
    first = FakeEditor("editor-a", ("Editor A",), instance_id="app-session-a")
    second = FakeEditor("editor-b", ("Editor B",), instance_id="app-session-b")
    registry.register(first)
    registry.register(second)
    router = Router(registry)
    now_s = 100.0
    for idx, (editor, phrase) in enumerate((
        (first, "YazSes, write to Editor A: First application receives this."),
        (second, "YazSes, write to Editor B: Second application receives this."),
    ), start=1):
        result = router.plan(phrase, command_mode=True, request_id=f"demo-{idx}")
        assert result.proposal is not None
        grant = Grant(editor.describe().destination_id, editor.instance_id,
                      frozenset({Operation.DRAFT}), expires_at_s=now_s + 30,
                      user_approved=True)
        outcome = router.execute_draft(result.proposal, grant, now_s=now_s)
        print(f"{editor.describe().destination_id}: {outcome.status.value}: {editor.content}")


if __name__ == "__main__":
    main()
