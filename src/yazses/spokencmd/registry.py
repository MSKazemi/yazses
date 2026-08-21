"""Which spoken capabilities are switched on, and the phrase each one answers to.

Separate from `router.py` because the router is pure routing and this is the
place that knows about `Config` and about the six feature packages. Keeping the
import of those packages *here* is also what makes the wiring honest: the daemon
imports this module, so `tests/test_feature_wiring_honesty.py` can see that
`yazses.spelling`, `yazses.math`, `yazses.code`, `yazses.snippets`,
`yazses.spokenregex` and `yazses.voicetimer` are genuinely reachable from an
entry point rather than being flagged wired by hand.

Every core imported below already existed, tested, with no caller. Nothing in
this module reimplements one; it supplies the verb, the config flag and the
ordering, which is the whole of what was missing.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from yazses.spokencmd.router import SpokenHandler, SpokenResult, prefixed, tidy

#: Order is fixed and matters only for determinism — the verbs are disjoint, so
#: no phrase can be claimed by two handlers.


def _spelling() -> SpokenHandler:
    from yazses.spelling.nato import spell_parse

    return prefixed("spelling", ("spell", "spell out", "spelling"), spell_parse)


#: Spacing rules, applied in order. Each is (pattern, replacement) and each is
#: positional on purpose — a blanket "close up around punctuation" gets `x = (a +
#: b)` wrong by turning it into `x =(a + b)`, so a bracket only closes up against
#: an identifier, which is what a call or a definition looks like.
_SPACING: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\s+([)\]},;:])"), r"\1"),        # no space before a closer or separator
    (re.compile(r"([(\[{])\s+"), r"\1"),           # no space just inside an opener
    (re.compile(r"(?<=\w)\s+([(\[])"), r"\1"),    # foo (x) -> foo(x); leaves `= (a + b)`
    (re.compile(r"(?<=\w)\s*\.\s*(?=\w)"), "."),  # self . name -> self.name
    (re.compile(r"\s+\."), "."),                    # a trailing dot never floats
)


def tighten_code(text: str) -> str:
    """Close up the spaces `spoken_symbols` leaves around punctuation. Pure.

    ``spoken_symbols`` substitutes word-bounded phrases, so the spaces that
    separated the spoken words survive into the output: "code def foo open paren x
    close paren colon" yields ``def foo ( x ) :``. That is correct for what the
    core promises — its own tests pin ``"x = ( a + b )"`` — and useless as code.

    So the spacing is fixed *here*, in the wiring, rather than in the core. The
    core is a symbol substituter shared with the command-safety tests, which rely
    on exactly what it emits today; a layout opinion belongs to the caller that
    wants code out of it.

    The rules stay conservative because this types into the user's editor: it
    closes up brackets, separators and attribute dots, and it does **not** try to
    guess operator spacing or indentation, which differ per language and would be
    wrong more often than right.
    """
    out = text or ""
    for pattern, replacement in _SPACING:
        out = pattern.sub(replacement, out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def _code() -> SpokenHandler:
    from yazses.code.spoken import spoken_symbols

    def convert(body: str) -> str:
        return tighten_code(spoken_symbols(body))

    return prefixed("code", ("code", "code mode"), convert)


def _math() -> SpokenHandler:
    from yazses.math.latex import spoken_to_latex

    return prefixed("math", ("math", "maths", "formula", "equation"), spoken_to_latex)


def _spokenregex() -> SpokenHandler:
    from yazses.spokenregex.build import nl_to_regex

    return prefixed("spokenregex", ("regex", "regular expression", "pattern for"), nl_to_regex)


def _snippets(entries: dict) -> SpokenHandler:
    from yazses.snippets.expand import expand_snippet

    def convert(body: str) -> str | None:
        return expand_snippet(body, entries)

    return prefixed("snippets", ("insert", "expand", "snippet"), convert)


def _voicetimer() -> SpokenHandler:
    """A timer reports itself and types nothing, so ``types=False``.

    The whole utterance is handed to `parse_timer_command`, which owns its own
    grammar and answers ``None`` for anything that is not a timer — this is the
    one capability whose trigger is not a leading verb, because "cancel the
    timer" and "set a timer for 25 minutes" do not share one. It is safe without
    the anchor that :func:`prefixed` applies for exactly the reason the others
    are not: the phrase must contain the word *timer* (or an alarm/reminder verb)
    **and** parse to a duration, so an ordinary sentence cannot satisfy it.
    """
    from yazses.voicetimer.parse import format_duration, parse_timer_command

    def match(text: str) -> SpokenResult | None:
        parsed = parse_timer_command(text or "")
        if parsed is None:
            return None
        verb, seconds = parsed
        if verb == "cancel":
            return SpokenResult(slug="voicetimer", message="Timer cancelled.",
                                action=("timer_cancel", None))
        return SpokenResult(
            slug="voicetimer",
            message=f"Timer set for {format_duration(int(seconds or 0))}.",
            action=("timer_set", int(seconds or 0)),
        )

    return SpokenHandler(slug="voicetimer", match=match, types=False)



def _condense(max_sentences: int) -> SpokenHandler:
    """"condense <a rambling paragraph>" types the tightened version.

    Deliberately operates on the *body of this utterance* rather than on text
    already injected. Condensing what is already on screen would mean selecting
    and replacing it, and that needs a real caret position — the same thing that
    keeps `bookmarks` and `hatselect` unwired (issue #162). Speaking the long
    version and receiving the short one needs no caret at all.
    """
    from yazses.condense.extract import condense

    def convert(body: str) -> str | None:
        return condense(body, max_sentences=max_sentences)

    return prefixed("condense", ("condense", "summarise", "summarize", "tighten"), convert)


def _diagramvox(flavor: str) -> SpokenHandler:
    """"diagram A goes to B if yes" types Mermaid (or DOT).

    Declines unless the utterance produced at least one **edge**. `parse_graph_utterance`
    answers a one-node `Graph` for any prose at all — "diagram the release process"
    parses to a single node — and rendering that emits a flowchart wrapper around a
    fragment of the user's sentence. An edge is the thing that makes an utterance a
    diagram rather than a phrase that began with the word.
    """
    from yazses.diagramvox.graph import parse_graph_utterance

    def convert(body: str) -> str | None:
        graph = parse_graph_utterance(body)
        if not graph.edges:
            return None
        return graph.to_dot() if flavor == "dot" else graph.to_mermaid()

    return prefixed("diagramvox", ("diagram", "flowchart", "graph"), convert)


def _spreadsheet() -> SpokenHandler:
    """Spoken grid movement -> a key sequence ("next cell" -> Tab).

    Only :func:`parse_grid_move` is wired, and the omission is deliberate rather
    than partial work. Its keys — Tab, Return, the arrows, Home/End, ctrl+arrow —
    mean the same thing in Excel, LibreOffice Calc, Google Sheets and an ordinary
    HTML table, so they are safe to send without knowing which one is focused.
    `parse_cell_reference` is not wired because jumping to "B7" needs an
    application-specific Go To binding (Excel and Calc do not agree on one), and a
    guessed shortcut does not fail visibly — it silently does something else in
    whatever window is focused.

    The trigger is an exact whole-utterance dictionary lookup, which is stricter
    than the ``^…$`` anchor :func:`prefixed` applies, so no sentence containing
    "move up" can be claimed by it.
    """
    from yazses.spreadsheet.grid import parse_grid_move

    def match(text: str) -> SpokenResult | None:
        keys = parse_grid_move(tidy(text))
        if not keys:
            return None
        return SpokenResult(slug="spreadsheet", action=("keys", keys))

    return SpokenHandler(slug="spreadsheet", match=match)


def _echo() -> SpokenHandler:
    """"play that back" / "play the word 'report'" replays your own captured audio.

    ``types=False``: this puts nothing on screen, so it runs even with no editable
    target focused — which is the point, because the case it exists for is checking
    a homophone by ear rather than by eye.

    The trigger is anchored here and **not** delegated to
    `resolve_playback_target`, which cannot be a trigger test: its documented last
    resort is "default: replay everything", so it answers a window for any
    non-empty utterance at all. Asking it "is this a playback request?" would get
    "yes" for every sentence the user dictates.
    """
    def match(text: str) -> SpokenResult | None:
        # The trigger is tested against the tidied phrase, but the *payload* is the
        # raw utterance. `tidy` strips outer quotes, and a quote is meaningful here:
        # `resolve_playback_target` reads "play the word 'report'" by its quoted
        # token, and a stripped closing quote drops it to the bare-token path where
        # a leading apostrophe stops it matching the span text at all — so the
        # request silently degrades to replaying the whole clip.
        if not _ECHO_TRIGGER.match(_strip_sentence_end(text)):
            return None
        return SpokenResult(slug="echo", action=("echo_play", (text or "").strip()))

    return SpokenHandler(slug="echo", match=match, types=False)


#: Anchored at both ends like every trigger built by :func:`prefixed`, and narrowed
#: to the shapes `resolve_playback_target` actually understands.
#:
#: A leading verb alone is not enough, which a test found rather than a review:
#: ``^(?:play|replay|repeat)\s+.+$`` claims **"repeat business"**. So the utterance
#: must also name what to replay — *that*, *back*, *again*, *all*, *last*, *first*,
#: *word* — or quote the word it wants. Bare ``replay`` is unambiguous and allowed;
#: bare ``play`` is not, because it is an ordinary verb with an ordinary object.
#: Whisper ends a short utterance with a full stop the user never said, so the
#: trigger has to tolerate one — but it must NOT strip quotes the way `tidy` does.
#: A quoted word is how the user picks *which* word to replay, and `tidy` takes the
#: closing quote off "play 'weather'", which stops the trigger matching at all.
_SENTENCE_END = " \t\r\n.,!?;:\u2026"


def _strip_sentence_end(text: str) -> str:
    return (text or "").strip().strip(_SENTENCE_END).strip()


_ECHO_KEYWORDS = r"that|back|again|all|last|first|word"
_ECHO_TRIGGER = re.compile(
    r"^replay$"
    rf"|^(?:play|replay|repeat)\s+(?:.*\b(?:{_ECHO_KEYWORDS})\b.*|['\"].+['\"])$",
    re.IGNORECASE,
)

def _specs(config):
    """``(slug, enabled, build)`` for every spoken capability, in routing order.

    Each flag is read **explicitly** — ``config.spelling.enabled``, not
    ``getattr(config, slug).enabled``. That is not style. `scripts/config_status.py`
    finds config keys that nothing reads by scanning the source for the attribute,
    and a dynamic lookup is invisible to it: the first draft of this module used
    ``getattr`` and `tests/test_firstrun_seeds_only_live_keys.py` correctly reported
    that a fresh install seeds ``[spelling] enabled``, "which no running code
    reads". The key *was* read. The guard could not see it, and a guard that cannot
    see a real reader will not see a missing one either.
    """
    return (
        ("spelling", config.spelling.enabled, _spelling),
        ("code", config.code.enabled, _code),
        ("math", config.math.enabled, _math),
        ("spokenregex", config.spokenregex.enabled, _spokenregex),
        ("snippets", config.snippets.enabled,
         lambda: _snippets(dict(config.snippets.entries or {}))),
        ("voicetimer", config.voicetimer.enabled, _voicetimer),
        ("condense", config.condense.enabled,
         lambda: _condense(int(config.condense.max_sentences))),
        ("diagramvox", config.diagramvox.enabled,
         lambda: _diagramvox(str(config.diagramvox.flavor or "mermaid").lower())),
        ("spreadsheet", config.spreadsheet.enabled, _spreadsheet),
        ("echo", config.echo.enabled, _echo),
    )


def enabled_slugs(config) -> tuple[str, ...]:
    """The spoken capabilities switched on in ``config``, in routing order.

    Split out from :func:`build_handlers` so the daemon and the CLI can report
    *which* are live without constructing them.
    """
    return tuple(slug for slug, on, _build in _specs(config) if on)


def build_handlers(config) -> Sequence[SpokenHandler]:
    """Construct the handlers for every capability enabled in ``config``.

    Cores are imported inside their builders, so a machine with all six off pays
    for none of them — the same lazy-import discipline the rest of the daemon uses
    to keep startup cheap.
    """
    return [build() for _slug, on, build in _specs(config) if on]
