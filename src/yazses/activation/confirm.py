"""Confirmation policy for intent-carrying activation sources (#138).

Once a source can emit an intent (#137), a failure mode arrives that the
hold-to-talk key never had: **an action the user never consciously requested.**

The numbers make that concrete. Best reported silent-command accuracy is 96–97%
over 10–30 words (Tang, arXiv:2504.13921; Kurotaki, doi:10.1002/aisy.70440),
measured on 3–4 subjects, in-session — the optimistic end. So roughly **one
command in thirty is wrong**, and out-of-session, cross-subject use is worse.

Typing a wrong word is recoverable; executing a wrong *command* may not be. So
the policy is keyed on **confidence × consequence**, not confidence alone:

======================  ====================  ====================
                        reversible            irreversible
======================  ====================  ====================
confidence ≥ threshold  act                   **confirm**
confidence < threshold  confirm               **confirm**
confidence < floor      reject                reject
======================  ====================  ====================

**Why irreversible always confirms, at any confidence.** A threshold cannot fix
this. To get the expected number of unrequested destructive actions near zero
you would need a per-command error rate the literature does not report for any
non-invasive decoder — and the 96% figure is in-session, on a handful of
subjects, which is the number most likely to degrade in the field. Gating on
consequence costs one toast on an action the user takes rarely, and removes the
class of outcome that cannot be undone. This generalises ADR-v2-010's
``needs_confirm``, which already does exactly this for gaze-routed closes.

**Why the default threshold is 0.90.** At the reported 96–97% accuracy a
decoder's own confidence is the only signal available for separating its good
calls from its bad ones. 0.90 sits below the reported operating point, so a
well-calibrated source acting near its published accuracy is not made unusable
by constant prompting, while the tail it is least sure about — where its errors
concentrate — is routed to a confirmation instead of an action. It is a
configurable starting point (``[activation] confirm_threshold``), not a claim
that 0.90 is optimal for any particular device; a source that publishes
calibration data should be tuned against it.

**Why the floor is 0.50.** Below an even chance the label carries less
information than a coin flip, and prompting the user to confirm a guess is worse
than silence: it trains them to dismiss prompts, which is how a confirmation
step stops being a safety mechanism.
"""

from __future__ import annotations

from enum import Enum

# Default gates. Justified above from the reported accuracy figures; both are
# overridable via [activation] in config.toml.
DEFAULT_CONFIRM_THRESHOLD = 0.90
DEFAULT_REJECT_FLOOR = 0.50


class Consequence(Enum):
    """Whether an action can be taken back by ordinary means."""

    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


class Decision(Enum):
    """What the daemon should do with an intent."""

    ACT = "act"
    CONFIRM = "confirm"
    REJECT = "reject"


# Actions an ordinary undo in the focused app puts back — an explicit allow-list,
# drawn from the tables in `commands/dispatch.py`.
#
# This is an allow-list rather than a deny-list on purpose. A deny-list answers
# "is this one of the dangerous ones I thought of?", so a command added later
# defaults to *safe* and executes silently on a 96%-accurate decoder. Listing
# what is recoverable inverts that: the unclassified case confirms, which costs
# one toast and cannot cost data. `save` is deliberately absent — writing over a
# file on disk is not in the editor's undo stack.
_REVERSIBLE_ACTIONS: frozenset[str] = frozenset({
    # caret movement and selection change nothing
    "arrow_up", "arrow_down", "arrow_left", "arrow_right",
    "line_home", "line_end", "page_up", "page_down",
    "go_to_line", "select_all", "select_to_end",
    "press_escape", "press_tab", "press_enter", "press_backspace",
    # text edits the app's undo stack owns
    "undo", "undo_n", "copy", "paste", "cut", "comment",
})

# Known-irreversible actions, named explicitly. This set is *not* what the
# runtime consults — unknown already falls through to irreversible — but it
# records the deliberate judgement for each shipped command, and lets a test
# assert that every action in `commands/dispatch.py` appears in exactly one of
# these two sets. Without it, "unclassified" and "decided to be dangerous" would
# be indistinguishable.
_IRREVERSIBLE_ACTIONS: frozenset[str] = frozenset({
    "save",            # writes over the file; not in the editor's undo stack
    "delete_lines",    # multi-line removal; recoverable only if undo is reached first
    "delete_words",
})


def classify_consequence(action: str) -> Consequence:
    """Classify a command action. Unknown actions are treated as irreversible.

    Defaulting unknown to irreversible is the safe direction: a command nobody
    remembered to classify gets a confirmation prompt, which is a mild
    annoyance, rather than silent execution, which is the failure this exists to
    prevent. `tests/test_activation_intent.py` pins every action the dispatcher
    can currently produce, so adding one without deciding its consequence fails
    in CI rather than in someone's editor.
    """
    return (
        Consequence.REVERSIBLE
        if action.strip().lower() in _REVERSIBLE_ACTIONS
        else Consequence.IRREVERSIBLE
    )


def decide(
    confidence: float,
    consequence: Consequence,
    *,
    threshold: float = DEFAULT_CONFIRM_THRESHOLD,
    floor: float = DEFAULT_REJECT_FLOOR,
) -> Decision:
    """Decide act / confirm / reject for one intent. Pure and total.

    ``floor`` is checked first: a sub-chance guess is dropped outright rather
    than turned into a prompt, including for irreversible actions.
    """
    if confidence < floor:
        return Decision.REJECT
    if consequence is Consequence.IRREVERSIBLE:
        return Decision.CONFIRM
    return Decision.ACT if confidence >= threshold else Decision.CONFIRM
