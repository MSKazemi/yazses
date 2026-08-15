# ADR-v2-131 — What cloud escalation could ever cover, once the privacy rules are applied

**Status:** Accepted (2026-08-16) · supersedes the *scope* of [[adr-v2-126-cloud-escalation]];
no implementation is scheduled
**Context links:** [[adr-011]] (offline by default, opt-in cloud, no silent fallback),
[[adr-019-egress-inventory-and-escalation]] (§2 escalation rules, §3 what may never
escalate), [[adr-v2-126-cloud-escalation]] (the deferred design this narrows),
[[adr-v2-128-meeting-minutes-generation]] (defers cloud minutes *to* ADR-126 — the
conflict this ADR resolves), [[adr-016-dependency-budget]]

## Context

ADR-v2-126 designed provider-pluggable cloud transcription and deferred it, recording
guardrails so the offline feature would not be built in a way that precluded it. It is a
good decision document and a poor build spec, and it was written before
[[adr-019-egress-inventory-and-escalation]] existed.

ADR-019 changed the picture in two ways ADR-126 could not anticipate.

**First, §3 names three categories that may never leave the machine at all**, whatever
guardrails are offered: voiceprint embeddings ("biometric, irrevocable, and derived
without the speaker necessarily being the consenting user"), the learning corpus in whole
or in part ("a consent prompt at upload time cannot be informed consent about data
gathered before the prompt existed"), and anything captured from a third party who did not
consent — explicitly "Meeting Mode audio and any speaker other than the operator. The
operator can consent for themselves and cannot consent for the room."

**Second, `tests/test_egress_inventory.py` makes the two send-paths a pinned number.**
`test_only_two_paths_can_send_what_the_user_said` asserts `len(SEND) == 2` and says in its
own failure message that a third "needs an ADR, not a test edit". Registering a cloud
adapter honestly fails that test by construction, which is the intended behaviour.

Applying §3 to the list of features that are actually compute-bound produces a result
worth stating plainly, because it is narrower than anyone assumed:

| Candidate | Compute-bound? | Survives ADR-019 §3? |
|---|---|---|
| Meeting minutes ([[adr-v2-128-meeting-minutes-generation]]) | Yes — "minutes of CPU compute, not seconds", and an hour's transcript exceeds a small model's context | **No.** Its input is the room. |
| Personal / atypical-speech LoRA ([[adr-v2-009]], [[adr-v2-021]]) | Yes — the heaviest thing in the design set | **No.** Its input *is* the corpus. |
| Pure-vision screen commanding ([[adr-v2-024]]) | Yes — deferred on VLM latency | **No.** Screen frames of someone's desktop. |
| Batch `yazses transcribe` of the operator's own recording | Yes — the ASR pass dominates; diarization is cheap (~45 min in ~30 s) | **Yes.** |

Everything heavier than batch transcription is heavy *because* it processes the corpus,
the room, or the screen. That is not a coincidence to be engineered around: the same
property that makes a workload expensive here — lots of accumulated personal audio — is
the property that makes it unsendable.

A second, smaller finding matters for the design. **YazSes already ships a two-step,
off-by-default, warns-loudly path for sending dictated text to an arbitrary host.**
`postprocess/llm_cleanup.py` is confined to loopback by `is_loopback_endpoint()`, checked
per call rather than at construction, with `llm_allow_remote_endpoint = False` as a
documented escape hatch that `yazses doctor` warns about. ADR-019's table describes that
path as "confined to loopback" and understates it. Whatever cloud escalation eventually
looks like, that is the shape to copy rather than a new consent system to invent.

## Decision

**1. Escalation, if it is ever built, covers exactly one thing: `yazses transcribe` on a
file the operator asserts is their own voice.** Not the daemon, not dictation, not
meetings, not the corpus, not the screen. ADR-126's provider adapter design stands for
that scope; its scope does not.

**2. Meeting minutes may not escalate, and [[adr-v2-128-meeting-minutes-generation]] is
amended here rather than left in conflict.** ADR-128 defers cloud minutes to ADR-126;
ADR-019 §3 forbids uploading Meeting Mode audio. §3 wins — it is the later and more
specific rule, and it is the one enforced by a test. Local minutes stay as designed, and
"slow" is the honest answer for a one-hour meeting, not "send it somewhere".

**3. Landing it is one commit that edits five things, and the ADR must say so up front:**
the `SEND` list in `tests/test_egress_inventory.py`, ADR-019's inventory table, the
sentence in `docs/privacy-statement.md` that reads "There is no third path", the README's
privacy claim, and `RecimportConfig`. A change that edits the test without the prose is
the failure mode this enumeration exists to prevent.

**4. The consent mechanism is the `llm_cleanup` shape, not a new one.** Off by default; a
per-invocation flag; the key from a user-named environment variable, never `config.toml`;
a syntactic check before any socket is opened; a warning that names the destination host.
ADR-011's "Yes / Yes-for-session / No" prompt describes machinery that does not exist in
this codebase — its Implementation section still refers to `yazses-core/src/cloud_consent.rs`
from the abandoned Rust v1, and there is no `privacy-gate` CI job either. Anyone reviving
this builds from zero; they should not believe otherwise because an ADR says it is there.

**5. ADR-019's "visible while it happens" requirement needs a CLI equivalent.** It reasons
from the tray's state colour, and `yazses transcribe` never touches the tray. A progress
line naming the host, printed for the duration, is the equivalent — decided here so the
requirement is satisfiable rather than quietly dropped.

**6. Still not scheduled.** This ADR narrows what would be acceptable. It does not ask for
the work, and `docs/research/directions.md` continues to list cloud escalation under
"deliberately not pursued", with the reasoning that it "would trade the only durable
advantage for an accuracy delta nobody has measured". Measuring that delta is the honest
prerequisite, and nobody has.

## Consequences

**Good.** The contradiction between two accepted ADRs is resolved in writing rather than
discovered by whoever tries to implement one of them. The scope is now small enough to
reason about: one CLI command, one file at a time, the operator's own voice.

**Accepted cost.** Meeting minutes on a slow machine stay slow. That is a real limitation
for a real use case, and the alternative was uploading other people's speech.

**What would reverse this.** For §1: a measured WER delta on hard audio large enough to
justify the trade, plus a provider whose retention policy survives reading. For §2:
nothing short of every participant consenting individually, which is not a feature, it is
a legal arrangement.

**What this does not do.** It writes no code, adds no dependency, and changes no default.
The egress inventory still enumerates seven connections and two send paths, and the test
still fails anyone who quietly adds a third.
