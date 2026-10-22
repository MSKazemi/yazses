# ADR-030 — Direction: the offline microphone for the agent era, and a breadth freeze

**Status:** Accepted (2026-10-22)
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-011]] (zero telemetry, offline by default),
[[adr-016-dependency-budget]] (features pay for themselves),
[[adr-019-egress-inventory-and-escalation]] (every way data can leave, and what never may),
[[adr-020-agent-protocols]] (the MCP server, `ask_human`, and what YazSes must not become),
[[adr-021-invest-in-error-cost]] ("Investment follows evidence"),
[[adr-v2-132-assisted-bug-reporting]] (option (b): prepare, never send),
[[adr-031-send-to-prefill-handoff]], [[adr-032-mcp-discoverability]].

Evidence labels: **[M]** measured in this repository on `origin/main` `f821884e` ·
**[F]** a primary source says so · **[O]** engineering judgement · **[U]** not verified.

---

## Context

YazSes is four months old and has grown along every axis at once. On 2026-10-22 the feature
registry holds **149 capabilities, of which 30 are designed but not wired** — `features
enable` refuses them [M] (`yazses.system.features`). The design record holds 179 ADRs.
The September and October effort went mostly to eye and hands-free control.

Three observations make breadth the wrong axis to keep growing:

1. **What is advertised is not all confirmed.** The
   [validation matrix](../../docs/validation-matrix.md) has reports of text actually typed
   into applications on **Linux GNOME X11 only** — graded *Reported*, with no version
   stated. No macOS row records typed text on a current build. On Windows, installation,
   launch and update were exercised on 2026-10-22 (pending in the matrix), but capture →
   transcription → injection from the packages is still UNVERIFIED. GNOME Wayland has a
   capture report and no injection report [M]. The README already labels
   macOS and Windows *preview*; the comparison pages do not make that distinction.
2. **The demand that exists is narrow and specific.** People now dictate into terminal
   coding agents and AI chat boxes — long prompts with thinking pauses, where a silence
   endpointer truncates mid-thought and a cloud dictation service sees the prompt [O]. YazSes
   already types into any focused window, including a terminal and an SSH session; its
   hold-to-talk never truncates; staged mode lets the user review before committing; and
   nothing leaves the machine [M]. That is a better fit for this user than for any user the
   breadth was built for.
3. **ADR-021 already set the rule and it was not followed.** "Investment follows evidence."
   The hands-free stack has no observed real user yet; the stack itself is sound and stays,
   but it does not earn more investment until someone uses it [M].

The alternative proposed in October — a single voice interface that routes spoken intents
to cloud AI services ("write an email" → a chat service, a mail account) — was assessed and
rejected (§Alternatives). It is a product funded vendors already ship from both ends, and it
would make YazSes's only durable advantage — nothing leaves the machine — the first thing it
gives up.

## Decision

### 1. What YazSes is

> **The offline, keyboard-level voice input for the agent era — Linux-first,
> Wayland-correct, hands-free-capable — that any agent can plug into.**

YazSes is the *microphone*, not the *assistant*. It turns speech into text where the
cursor is, and it offers that capability to other programs through narrow, local,
consent-first interfaces. It does not decide what the user meant to *do*, and it does not
act in a third-party service on the user's behalf.

### 2. Four pillars, in this order

**Pillar 1 — Make what is advertised true before adding anything.**

1. macOS and Windows stay labelled **preview** until a named human records dictation on a
   current build in the validation matrix, graded *Verified (HW)* under the
   [evidence standard](../../docs/contribute/validation.md); the label comes off per OS, not
   together. Linux X11 gets the same versioned *Verified* record, so the one platform the
   project leads with is no longer resting on undated reports. The
   docs (README, comparison pages, platform support) must not claim more than the matrix.
2. Wayland dictation is verified on hardware (at least GNOME and KDE) before any page claims
   "full Wayland".
3. The engine question is answered by measurement: Parakeet TDT already measures better WER
   than Whisper here (2.06 % vs whisper-large-v3's 3.23 %, see `docs/benchmarks.md`). A
   change of default engine is an L3 config change and gets its own ADR; before that, a
   Parakeet that fails to load must say so loudly instead of falling back silently.
4. Unwired capabilities are not advertised as features. `docs/v2-features.md`, the README
   and the comparison pages describe what `features enable` will actually turn on.

**Pillar 2 — The agent-era user, through two on-brand bridges.**

1. **"Send to"** ([[adr-031-send-to-prefill-handoff]]): dictated text is handed to a
   desktop AI client (Claude, Codex) **pre-filled, never sent**. The user presses Enter.
2. **Discoverable MCP** ([[adr-032-mcp-discoverability]]): the existing `yazses mcp-server`
   becomes installable in one step (an `.mcpb` bundle, an MCP registry entry), and
   `ask_human` listens until the user stops speaking instead of for a fixed time.

Both run through mechanisms ADR-019 already classifies: a URL handed to another program,
and a stdio child process. Neither adds an egress path.

**Pillar 3 — Distribution before new material.** Getting YazSes in front of the people in
§Context is owner work (community posts, directories, editorial tips). New campaign assets
wait until the existing ones are in use. This pillar has no code; it is recorded so the
other three are not mistaken for the whole plan.

**Pillar 4 — Decide with evidence.** The leading signal is a **substantive issue or
discussion from someone who is not a contributor**. Stars are a lagging signal and are not
a target in this record.

### 3. A breadth freeze, starting after the 2026-10-22 wave

The code-only wave in progress on 2026-10-22 (wiring of already-advertised capabilities,
`features repair`, idle unload for ADR-029, and three hands-free capabilities: morse,
interruptible proof-reading and the mouth switch) finishes as approved.

After it lands, until the first substantive issue from a non-contributor:

- **No new ADR waves** and no new registry capabilities outside the four pillars.
- **Allowed:** bug fixes; wiring a capability that is already advertised (that is Pillar 1);
  removal; tests, CI and packaging; documentation; and work on Pillars 1–2.
- **The hands-free stack stays opt-in and maintained.** Bugs are fixed, it is not removed,
  and it gets no new capabilities until one real hands-free user is observed (ADR-021).
- A proposal outside the pillars during the freeze is written down as a *Proposed* ADR or an
  `evergreen:research` issue and stops there.

Lifting the freeze is a decision recorded as an amendment to this ADR, with the evidence
that triggered it.

### 4. What we do not build

- Intent routing to cloud services ("write an email" → a chat service or a mail account).
- A wake-word, always-listening assistant.
- Any action that **sends** on the user's behalf in a third-party service. Prefill is the
  boundary; Enter belongs to the user.
- A cloud transcription path. [[adr-v2-126-cloud-escalation]] stays design-only, as
  [[adr-v2-131-cloud-escalation-scope]] scoped it.

## Consequences

- **Positive.** The project's work concentrates where the evidence points, and the
  advertised surface converges on the verified one — which is what a reviewer, a distro
  packager or a launch audience checks first. The two bridges reuse code that exists
  (`system/browser.py::open_url`, `mcp/server.py`), so Pillar 2 is small.
- **Negative.** Contributors who arrived for eye control, Android or new capability waves
  see slower movement there. The Android programme (#81) is unaffected in *design*; it is a
  separate surface and follows its own milestones, but it competes for the same
  maintainer hours.
- **Tracking.** Pillar 1 items go to the existing *Install anywhere*, *Hear better* and
  *Welcome mat* milestones; Pillar 2 gets its own outcome milestone. Each item is a
  delivery issue under [`design/milestone-policy.md`](../milestone-policy.md).
- **Docs.** `docs/roadmap.md` states the direction and the freeze in user-facing words, and
  a use-case page describes YazSes for AI-agent users with only what exists today.

## Alternatives considered

- **One voice interface to all AI systems (cloud intent routing).** Rejected. Desktop AI
  clients already accept typed and spoken input themselves, and mail and office suites ship
  their own assistants [O]. Routing spoken intents to them needs network calls carrying
  what the user said, which ADR-019 allows only with explicit, per-path escalation and
  which reverses the project's founding property. The useful kernel of the idea — get my
  words into the AI tool I already use, without a cloud transcriber — is Pillar 2.
- **Keep the current breadth and add the bridges alongside.** Rejected. It leaves 30
  unwired capabilities advertised and two of three desktop operating systems unconfirmed,
  and it is the course ADR-021 already warned against.
- **Freeze now, parking the in-flight hands-free work.** Rejected by the decider: the
  2026-10-22 wave was approved the same day, its capabilities are already designed and
  tested, and parking finished work costs more than landing it.
