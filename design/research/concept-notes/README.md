# Concept notes — where ten shipped features started

These are the original idea pitches for ten YazSes v2 features, kept private while the
features were unbuilt (an unshipped idea reads as a promise) and published here now that
each one has actually shipped as an off-by-default, opt-in capability with a real ADR or
spec. Each note is short on purpose: the technical design lives in the linked ADR/spec,
not here. What these add is the "why we tried this" the ADRs themselves don't carry —
and, honestly, where the original pitch turned out to be right or wrong once built.

| Note | Feature | Shipped as |
|---|---|---|
| [Cocktail Filter](2026-06-14-cocktail-filter.md) | Filter out other voices in the room | [`v2-cognitive-layer/02-cocktail-filter.md`](../../v2-cognitive-layer/02-cocktail-filter.md) — gate layer shipped, off by default after live testing found it unreliable on short windows |
| [Glance-Type](2026-06-14-glance-type.md) | Look-to-pane dictation targeting | [`v2-cognitive-layer/03-glance-type.md`](../../v2-cognitive-layer/03-glance-type.md), [ADR-v2-010](../../adr/adr-v2-010-gaze-routed-dictation.md) |
| [Polyglot Switch](2026-06-14-polyglot-switch.md) | Configured-pair code-switch dictation | [`v2-cognitive-layer/04-polyglot-switch.md`](../../v2-cognitive-layer/04-polyglot-switch.md), [ADR-v2-008](../../adr/adr-v2-008-code-switch.md) |
| [Voiceprint Mind](2026-06-14-voiceprint-mind.md) | Personal vocabulary/accent adaptation | [`v2-cognitive-layer/01-voiceprint-mind.md`](../../v2-cognitive-layer/01-voiceprint-mind.md), [ADR-v2-009](../../adr/adr-v2-009-personal-adapter.md) |
| [Prosody Ink](2026-06-14-prosody-ink.md) | Pause→paragraph, stress→bold | [ADR-v2-002](../../adr/adr-v2-002-prosody-autoformat.md) |
| [Punch-In](2026-06-14-punch-in.md) | Re-speak a phrase to fix it | [`specs/punch-in.md`](../../specs/punch-in.md) |
| [Dysfluency-Friendly Mode](2026-06-19-dysfluency-friendly-mode.md) | Forgiving endpointing + repetition collapse | [ADR-015](../../adr/adr-015-dysfluency-friendly-mode.md) |
| [Ghost Ahead](2026-06-14-ghost-ahead.md) | Pre-warm the decoder before hold-release | [`specs/ghost-ahead.md`](../../specs/ghost-ahead.md) |
| [Read-Back Loop](2026-06-14-read-back-loop.md) | Hear the transcript, confirm/correct by voice | [`specs/read-back-loop.md`](../../specs/read-back-loop.md), [ADR-v2-042](../../adr/adr-v2-042-personal-readback-voice.md) |
| [Spoken Recall](2026-06-19-spoken-recall.md) | Ask your own past dictation a question | [ADR-v2-005](../../adr/adr-v2-005-spoken-recall.md) |

All ten features ship **off by default**. Six other idea cards from the same batch —
Say Macro, Uncertainty Ink, Spoken Agent, Ambient Scribe, Mid-Thought Undo, and Sotto
Voce — have not shipped and stay private, per `design/README.md`'s visibility contract:
an idea without a shipped decision behind it reads as a promise.
