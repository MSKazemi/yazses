# Ghost Ahead — origin note

> **Written:** 2026-06-14 · **Owner:** Mohsen Seyedkazemi Ardebili
> **Shipped as:** [`design/specs/ghost-ahead.md`](../../specs/ghost-ahead.md)
> **Tier:** `design/` — public. Historical origin note; the spec above is the current
> source of truth.

## The idea

The card names its own seduction and then talks itself out of it: the "autocomplete for
speech" dream — a model guessing the next few words a user was *about to say* — was
rejected as not real yet, on the evidence that even the best precedent (code-completion
ghost text, on far more structured input than free speech) is ignored roughly two-thirds
of the time. The idea that survived the filter was narrower and evidenced: don't predict
*what* comes next, predict *when* the user is about to stop — from prosody, falling pitch,
a lengthening pause, a partial transcript flattening out — and use that early signal to
pre-warm the decoder so the gap between "I finished talking" and "the text appears"
shrinks toward zero, with the authoritative commit always staying on the real hold-release
so a wrong guess can never truncate what the user said.

## What shipped

The pre-warm mechanism shipped as `EndpointAnticipator` in `src/yazses/stt/endpoint.py`,
wired to the `ghost-ahead` feature toggle. It carries no user-facing behaviour to
configure — the spec's own summary is "nothing to do — the decoder pre-warms for faster
first words" — which matches the original card's framing of this as latency plumbing, not
a new interaction.
