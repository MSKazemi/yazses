"""A map-reduce window sized in turns does not bound anything the model cares about.

`meeting/notes.py` split the transcript into windows of 40 **turns**. A turn is one
word or a five-minute monologue, so the prompt size was unbounded, and llama.cpp
fails at two different sizes in two different ways:

* ``len(prompt_tokens) >= n_ctx`` raises ``ValueError``. `generate_minutes` caught it,
  logged, and moved on — so that slice of the meeting was **absent from the minutes**
  and the document did not say so. Minutes that quietly omit part of a meeting are
  worse than none: the reader cannot tell which part is missing, and the transcript
  they would check against is the thing they were trying not to read.
* Below that but above ``n_ctx - max_tokens``, llama.cpp does not raise — it silently
  clips ``max_tokens`` to what is left. With the GBNF grammar on, generation is then
  cut off mid-object and the JSON never closes.

The second band was reachable with the shipped defaults on ordinary meetings: of the
meetings stored on the author's machine, the two with a real transcript peaked at
~3676 and ~3459 estimated tokens per 40-turn window, both past ``4096 - 1024 = 3072``,
one of them at 90% of the hard limit after fifteen minutes.
"""

from __future__ import annotations

import logging

from yazses.meeting.notes import (
    CHARS_PER_TOKEN,
    Minutes,
    format_turns,
    generate_minutes,
    window_budget_chars,
    window_turns,
)
from yazses.recimport.align import Utterance


class _Cfg:
    notes = True
    notes_model = "/nonexistent.gguf"
    notes_window_turns = 40
    notes_max_tokens = 1024
    notes_ctx_tokens = 4096


def _turns(count: int, words: int) -> list[Utterance]:
    return [
        Utterance("speaker_0", float(i), float(i) + 1.0, " ".join(["word"] * words))
        for i in range(count)
    ]


def test_the_budget_leaves_room_for_the_answer_not_just_the_question() -> None:
    """`max_tokens` is not extra space on top of the context — it comes out of it."""
    budget = window_budget_chars(4096, 1024)
    assert budget / CHARS_PER_TOKEN < 4096 - 1024, (
        "a full window would leave the model no room to finish its JSON"
    )
    assert budget > 0


def test_a_forty_turn_window_of_long_turns_is_split() -> None:
    """The exact shape the shipped default got wrong: the turn count is satisfied
    and the prompt is far past the context anyway."""
    turns = _turns(40, 120)
    budget = window_budget_chars(4096, 1024)

    unbounded = window_turns(turns, 40)
    assert len(unbounded) == 1
    assert len(format_turns(unbounded[0])) > budget, "fixture no longer overflows"

    windows = window_turns(turns, 40, budget)
    assert len(windows) > 1
    for w in windows:
        assert len(format_turns(w)) <= budget, len(format_turns(w))


def test_no_turn_is_dropped_or_reordered_by_the_split() -> None:
    """Splitting must not cost content — that is the failure it exists to prevent."""
    turns = _turns(37, 90)
    windows = window_turns(turns, 40, window_budget_chars(4096, 1024))
    rejoined = " ".join(u.text for w in windows for u in w)
    assert rejoined.split() == " ".join(u.text for u in turns).split()


def test_short_meetings_window_exactly_as_before() -> None:
    """Most meetings are nowhere near the limit and must not be re-cut."""
    turns = _turns(90, 6)
    assert window_turns(turns, 40, window_budget_chars(4096, 1024)) == window_turns(turns, 40)


def test_one_turn_longer_than_the_whole_budget_is_split_not_dropped() -> None:
    """A monologue is exactly the turn minutes must not lose, and it fits no window
    at all unless it is broken up."""
    budget = window_budget_chars(4096, 1024)
    long_turn = [Utterance("speaker_0", 0.0, 1.0, " ".join(["word"] * (budget // 2)))]
    windows = window_turns(long_turn, 40, budget)
    assert len(windows) > 1
    for w in windows:
        assert len(format_turns(w)) <= budget
    rejoined = " ".join(u.text for w in windows for u in w)
    assert rejoined.split() == long_turn[0].text.split()


def test_a_zero_budget_keeps_the_old_turn_only_behaviour() -> None:
    """`0` is the documented escape hatch, and it must mean what it used to."""
    turns = _turns(100, 120)
    assert window_turns(turns, 40, 0) == window_turns(turns, 40)
    assert window_turns(turns, 40, None) == window_turns(turns, 40)


def test_minutes_say_so_when_a_window_could_not_be_summarised(caplog) -> None:
    """The silent half of the defect. A window that fails is content the reader will
    never see; the minutes must admit it rather than looking complete."""
    calls: list[str] = []

    def llm(prompt: str) -> str:
        calls.append(prompt)
        if len(calls) == 2:
            raise ValueError("Requested tokens (5000) exceed context window of 4096")
        return '{"summary": "a window", "decisions": [], "action_items": []}'

    turns = _turns(80, 120)
    with caplog.at_level(logging.WARNING, logger="yazses.meeting.notes"):
        minutes = generate_minutes(turns, _Cfg(), llm=llm)

    assert isinstance(minutes, Minutes)
    assert len(calls) > 2, "the fixture did not produce multiple windows"
    assert minutes.summary.startswith("INCOMPLETE"), minutes.summary
    assert "1 of" in minutes.summary, minutes.summary
    assert any("incomplete" in r.getMessage() for r in caplog.records)


def test_the_gap_note_is_not_left_to_the_summariser_to_preserve(caplog) -> None:
    """The disclosure is stamped on the final minutes, never fed in as one more
    partial. The reduce step is a model told to "deduplicate and keep the most
    important points" — a warning about the summariser is exactly what it drops, and
    a disclosure that survives by luck is not a disclosure."""
    calls = {"n": 0}

    def llm2(prompt: str) -> str:
        if "Partials:" in prompt:
            # A reduce that throws the note away, which is entirely allowed of it.
            return '{"summary": "a tidy meeting", "decisions": [], "action_items": []}'
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("Requested tokens (5000) exceed context window of 4096")
        return '{"summary": "a window", "decisions": [], "action_items": []}'

    minutes = generate_minutes(_turns(80, 120), _Cfg(), llm=llm2)
    assert minutes is not None
    assert "INCOMPLETE" in minutes.summary, (
        "the reduce step dropped the disclosure and nothing put it back"
    )
    assert "a tidy meeting" in minutes.summary, "the real summary was discarded"


def test_minutes_are_unmarked_when_every_window_succeeded() -> None:
    """The marker must be evidence, not decoration."""
    def llm(prompt: str) -> str:
        return '{"summary": "fine", "decisions": [], "action_items": []}'

    minutes = generate_minutes(_turns(80, 120), _Cfg(), llm=llm)
    assert minutes is not None
    assert "INCOMPLETE" not in (minutes.summary or "")


def test_a_long_display_name_is_paid_for_rather_than_assumed() -> None:
    """`format_turns` puts the display name on every line. Forty lines of
    "Mohsen Seyedkazemi Ardebili: " is 1100 characters the window never counted."""
    from yazses.meeting.notes import line_overhead_chars

    assert line_overhead_chars(None) == 16
    assert line_overhead_chars({"speaker_0": "Ana"}) == 16
    names = {"speaker_0": "Mohsen Seyedkazemi Ardebili"}
    assert line_overhead_chars(names) == len(names["speaker_0"]) + 3

    turns = [
        Utterance("speaker_0", float(i), float(i) + 1.0, " ".join(["word"] * 40))
        for i in range(60)
    ]
    budget = window_budget_chars(4096, 1024)
    windows = window_turns(turns, 40, budget, line_overhead_chars(names))
    for w in windows:
        assert len(format_turns(w, names)) <= budget, len(format_turns(w, names))


def test_generate_minutes_actually_applies_the_budget() -> None:
    """The wiring, asserted separately from the policy. `window_turns` can grow a
    perfect budget parameter and `generate_minutes` can go on not passing it — which
    is the shape this repo has shipped before — so the prompts the model is really
    handed are measured here, not the helper that computes them."""
    prompts: list[str] = []

    def llm(prompt: str) -> str:
        prompts.append(prompt)
        return '{"summary": "s", "decisions": [], "action_items": []}'

    generate_minutes(_turns(40, 120), _Cfg(), llm=llm)

    budget = window_budget_chars(_Cfg.notes_ctx_tokens, _Cfg.notes_max_tokens)
    assert len(prompts) > 1, "the whole meeting still went to the model in one prompt"
    for prompt in prompts[:-1] or prompts:
        assert len(prompt) <= budget + 400, len(prompt)


def test_a_long_display_name_reaches_the_model_inside_the_budget() -> None:
    """Same wiring, with the label width that `format_turns` will really emit."""
    prompts: list[str] = []

    def llm(prompt: str) -> str:
        prompts.append(prompt)
        return '{"summary": "s", "decisions": [], "action_items": []}'

    names = {"speaker_0": "Mohsen Seyedkazemi Ardebili"}
    generate_minutes(_turns(60, 40), _Cfg(), llm=llm, speaker_names=names)

    budget = window_budget_chars(_Cfg.notes_ctx_tokens, _Cfg.notes_max_tokens)
    for prompt in prompts:
        assert len(prompt) <= budget + 400, len(prompt)


def test_the_budget_and_the_model_read_the_same_context_setting() -> None:
    """One context, one number. `_build_llm` hardcoded `n_ctx=4096` while the budget
    came from config, so raising `[meeting] notes_ctx_tokens` would have grown the
    windows past a model that had not moved — reintroducing the exact failure this
    setting exists to prevent."""
    import inspect

    from yazses.meeting import notes

    source = inspect.getsource(notes._build_llm)
    assert "n_ctx=4096" not in source, "the model context is hardcoded again"
    assert 'getattr(config, "notes_ctx_tokens"' in source
    assert "n_ctx=n_ctx" in source

    budget_source = inspect.getsource(notes.generate_minutes)
    assert 'getattr(config, "notes_ctx_tokens"' in budget_source


# --- the reduce step has the same context, and used to ignore it ----------------


def _fat_partial(n: int) -> list:
    """Realistically sized per-window summaries: ~600-character summary, three
    decisions, two action items. That is what a map step actually returns."""
    from yazses.meeting.notes import ActionItem

    return [
        Minutes(
            summary="x" * 600,
            decisions=["y" * 80] * 3,
            action_items=[ActionItem("Ana", "z" * 80), ActionItem("Bo", "z" * 80)],
        )
        for _ in range(n)
    ]


def _llama_like(reply: str, limit: int):
    """A stand-in that fails the way llama.cpp fails: over the context it raises,
    it does not truncate. A fake that accepts any prompt cannot catch this bug —
    which is the whole reason it survived."""

    def llm(prompt: str) -> str:
        if len(prompt) > limit:
            raise ValueError(
                f"Requested tokens ({len(prompt) // 3}) exceed context window of 4096"
            )
        return reply

    return llm


def test_the_reduce_prompt_stays_inside_the_same_context() -> None:
    """The reduce was one call over *every* partial. On realistic summaries it
    overflows a 4096-token context at about eight — and the meetings stored on this
    machine produce eleven and three. So past roughly twenty-five minutes the reduce
    always raised, always fell back to concatenation, and the user got a wall of
    per-window summaries labelled "minutes" with a `log.warning` as the only sign."""
    from yazses.meeting.notes import _REDUCE_PROMPT, reduce_partials

    budget = window_budget_chars(4096, 1024) - len(_REDUCE_PROMPT)
    seen: list[int] = []

    inner = _llama_like(
        '{"summary": "merged", "decisions": [], "action_items": []}',
        window_budget_chars(4096, 1024),
    )

    def llm(prompt: str) -> str:
        seen.append(len(prompt))
        return inner(prompt)

    result = reduce_partials(llm, _fat_partial(40), budget)
    assert isinstance(result, Minutes)
    assert seen, "the reduce never called the model at all"
    for size in seen:
        assert size <= window_budget_chars(4096, 1024), size


def test_a_long_meeting_is_actually_reduced_not_just_concatenated() -> None:
    """The point of the reduce is deduplication. Falling back to `_merge_partials`
    silently turns forty summaries into one long one."""
    from yazses.meeting.notes import _REDUCE_PROMPT, reduce_partials

    budget = window_budget_chars(4096, 1024) - len(_REDUCE_PROMPT)

    llm = _llama_like(
        '{"summary": "one tight summary", "decisions": ["d"], "action_items": []}',
        window_budget_chars(4096, 1024),
    )
    result = reduce_partials(llm, _fat_partial(40), budget)
    assert result.summary == "one tight summary", result.summary[:120]


def test_the_reduce_terminates_on_a_partial_bigger_than_the_budget() -> None:
    """The only way batching could fail to make progress. Merging is lossless where
    another pass would be endless."""
    from yazses.meeting.notes import reduce_partials

    huge = [Minutes(summary="x" * 5000), Minutes(summary="y" * 5000)]

    def llm(prompt: str) -> str:
        raise AssertionError("nothing fits, so nothing should be sent")

    result = reduce_partials(llm, huge, 100)
    assert "x" * 10 in result.summary and "y" * 10 in result.summary


def test_batching_keeps_every_partial_exactly_once() -> None:
    from yazses.meeting.notes import _minutes_to_json, batch_partials

    rendered = [_minutes_to_json(m) for m in _fat_partial(37)]
    batches = batch_partials(rendered, 4000)
    assert sorted(i for b in batches for i in b) == list(range(37))
    assert all(batches[i][-1] < batches[i + 1][0] for i in range(len(batches) - 1))


def test_a_single_partial_needs_no_model_call() -> None:
    from yazses.meeting.notes import reduce_partials

    def llm(prompt: str) -> str:
        raise AssertionError("a lone partial is already the answer")

    only = Minutes(summary="done")
    assert reduce_partials(llm, [only], 10_000) is only


# --- a window can fail by returning ---------------------------------------------


TRUNCATED = '{"summary": "We agreed to ship on Frid'
GOOD = '{"summary": "a window", "decisions": [], "action_items": []}'


def test_truncated_model_output_parses_to_nothing() -> None:
    """The premise. llama.cpp clips `max_tokens` to what the context leaves rather
    than raising, so the model is cut off mid-object and the tolerant parser — which
    exists so a chatty model still yields minutes — finds no closing brace and returns
    an empty object. No exception is raised at any point."""
    from yazses.meeting.notes import _parse_minutes, is_empty

    assert is_empty(_parse_minutes(TRUNCATED))
    assert is_empty(_parse_minutes(""))
    assert is_empty(_parse_minutes("Here are the minutes: everyone agreed."))
    assert not is_empty(_parse_minutes(GOOD))


def test_a_window_that_returns_nothing_is_counted_as_lost(caplog) -> None:
    """Counted as a success it is a window of the meeting that vanishes with no
    warning and no INCOMPLETE note — the same silent loss the note exists to prevent,
    arriving through the door the note does not watch."""
    calls = {"n": 0}

    def llm(prompt: str) -> str:
        if "Partials:" in prompt:
            return '{"summary": "the meeting", "decisions": [], "action_items": []}'
        calls["n"] += 1
        return TRUNCATED if calls["n"] == 2 else GOOD

    with caplog.at_level(logging.WARNING, logger="yazses.meeting.notes"):
        minutes = generate_minutes(_turns(80, 120), _Cfg(), llm=llm)

    assert minutes is not None
    assert "INCOMPLETE" in minutes.summary, minutes.summary
    assert any("nothing usable" in r.getMessage() for r in caplog.records)


def test_a_meeting_where_every_window_returns_nothing_yields_no_minutes() -> None:
    """Empty minutes are not minutes. Returning a blank document would be the same
    silent claim in its purest form."""
    assert generate_minutes(_turns(80, 120), _Cfg(), llm=lambda p: TRUNCATED) is None


def test_a_healthy_meeting_is_not_marked_incomplete(caplog) -> None:
    """The guard must fire rarely, or it teaches the reader to ignore the word. A
    window that summarises to anything at all counts as summarised."""
    def llm(prompt: str) -> str:
        if "Partials:" in prompt:
            return '{"summary": "the meeting", "decisions": [], "action_items": []}'
        return '{"summary": "", "decisions": ["we shipped"], "action_items": []}'

    with caplog.at_level(logging.WARNING, logger="yazses.meeting.notes"):
        minutes = generate_minutes(_turns(80, 120), _Cfg(), llm=llm)

    assert minutes is not None
    assert "INCOMPLETE" not in minutes.summary
    assert not [r for r in caplog.records if "nothing usable" in r.getMessage()]
