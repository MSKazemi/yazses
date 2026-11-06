# YazSes XR — transport comparison (XR-R03) and threat review (XR-R04)

**Status: PROPOSED, 2026-11-06. Documentation only, hardware-unverified, not reviewed by a maintainer.** No XR code exists in YazSes and none is planned: the one implementation attempt, PR #732, was closed unmerged by the owner on 2026-11-02 (see section 0). Nothing here lifts or scopes the [ADR-030](../adr/adr-030-agent-era-direction.md) breadth freeze, amends [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md) or [ADR-020](../adr/adr-020-agent-protocols.md), or chooses a transport. It records what each candidate transport would cost *if* the entry gate in [ROADMAP.md](ROADMAP.md) ever opened, so that the decision memo (XR-R05) does not have to start from the 2026-05 capability card.

It builds on [EVIDENCE.md](EVIDENCE.md) (XR-R02, the platform documentation audit) and inherits its limits: no VRChat client, headset or XR runtime was run for this note either.

**Method.** Code is cited as `path:line` at commit `8a72bbc6` (main, 2026-11-06). Platform facts come from EVIDENCE.md, which cites its primary sources with URLs and read dates; no new web source was read for this note. Two general protocol facts are from prior knowledge and are labelled where used. Anything phrased "should" or "must" in sections 3 and 4 is a proposal for XR-R05, not a decision.

## 0. What changed since the evidence log

| Item | Finding, 2026-11-06 | How checked |
|---|---|---|
| PR #732, "pure XR voice-input adapter … (library, not wired)" | **Closed unmerged** 2026-11-02T01:35:16Z. The owner's closing comment gives the reason: about 23,000 lines of XR library code nothing in YazSes uses, which conflicts with the ADR-030 freeze and with this proposal ("no XR implementation is planned"). The tip is archived, so the work can be restored. | `gh pr view 732` (read-only), state `CLOSED`, `mergedAt` null |
| EVIDENCE.md section 4, gate 1 said the closure was "not re-verified" | Now verified (row above). The gate is still **not met**. | as above |
| A `yazses[xr]` extra and a `ws://localhost:8765` server | **Neither exists.** No `websocket` or `osc` dependency in `pyproject.toml`, no `8765` and no `websockets` import under `src/yazses/`. The research card (`design/research/studies/yazses-innovation/output/capability_cards/cap-006.md:17`, `:100`, `:136`) and the gap analysis (`.../output/03_gap_analysis.md:110`) describe them as proposals, so those files are consistent and were left unchanged. | `grep` over `pyproject.toml` and `src/yazses/` at `8a72bbc6` |

## 1. The five candidates

The task in [TASKS.md](TASKS.md) names three transports. Two more are added because a decision memo that omitted them would be incomplete: the one YazSes already has (keystroke injection), and the local IPC socket that already exists.

- **T0 — no new transport.** The user dictates with ordinary YazSes into whatever window has focus, as today. For VRChat on a desktop this would mean typing into the client's own text field or keyboard. **Whether VRChat's keyboard accepts injected keystrokes was not tested and is unknown.**
- **T1 — in-process callbacks.** A Python function registered inside the daemon receives the final transcript.
- **T2 — OSC over UDP to `127.0.0.1:9000`.** One datagram per draft to VRChat's documented input port, `/chatbox/input` with `b = false` (EVIDENCE.md section 1).
- **T3 — loopback WebSocket server.** The 2026-05 card's design: a listener on `localhost:8765` streaming JSON events to any local client.
- **T4 — a scoped method on the existing IPC socket.** The daemon's JSON-RPC over `AF_UNIX`, created owner-only (`src/yazses/ipc/server.py:74-87`).

## 2. Comparison (XR-R03)

| | T0 injection | T1 in-process | T2 OSC/UDP | T3 WebSocket | T4 AF_UNIX IPC |
|---|---|---|---|---|---|
| **Who can consume it** | Any focused window that takes keystrokes | Only code in the daemon's own Python process: a mock, or a Python host | VRChat and other OSC-speaking apps on this machine | Any local process and **any web page in a local browser** (see T3 note) | Any process running as the same user that can open a Unix socket |
| **Reaches VRChat, Unity or a browser** | VRChat desktop: unknown. Others: whatever accepts typing | **No.** VRChat, Unity and browsers are separate processes | VRChat: yes, by its documented API. Unity: only with an OSC library in the scene | Yes, by design | Unity/.NET and native apps: yes. A browser: no |
| **New dependency** | None | None | None required (an OSC message is a short binary frame). A library would be a choice, not a need | A WebSocket library as a new optional extra; none is present today | None |
| **ADR-019 class** | Already accounted for: it is the product | No network primitive, so no new row | A `socket` import trips `tests/test_egress_inventory.py`. It carries dictated text out of the process, so it is a **SEND**. `test_only_two_paths_can_send_what_the_user_said` asserts `len(SEND) == 2` (`tests/test_egress_inventory.py:393-404`), and ADR-019's defended sentence ("two code paths can send your words anywhere", `design/adr/adr-019-egress-inventory-and-escalation.md:162-164`) would change. Needs an ADR-019 amendment and a deliberate test change | A loopback listener is registered like `remote/agent.py` under `LOCAL_BOUND` (`tests/test_egress_inventory.py:74-79`), but unlike that one it would hand dictated text to clients it did not choose. Reading: a SEND to an unbounded set of local consumers. Needs an ADR-019 amendment | Stays in `LOCAL_IPC` (`tests/test_egress_inventory.py:66-68`); no egress row. Adding a method is a public-interface (L3) change per AGENTS.md |
| **Other ADR conflict** | None | None | None found | **ADR-020 §2 says no HTTP server**, because a bound port replaces a structural guarantee with a configuration one (`design/adr/adr-020-agent-protocols.md:48-58`); a genuine need is "a new ADR that supersedes this" (`:61-62`). A WebSocket opens with an HTTP upgrade request (RFC 6455; prior knowledge, not re-read today), so it falls under that section | None. It is the boundary ADR-020 relies on |
| **Lifecycle** | None new | Lives and dies with the daemon; no port, no session | Stateless datagrams; no connection to open or close. No acknowledgement: "sent" can never be shown as "delivered" (EVIDENCE.md section 2, item 4) | Port allocation and conflicts, start/stop with the daemon, per-client sessions, tokens, rotation, backpressure, reconnect | Socket already managed by the daemon; a streaming method would add per-client subscriptions and backpressure |
| **Who else can read the text** | The focused window, as today | Nobody outside the process | **Whatever process holds UDP port 9000.** If VRChat is not running, any local program can bind it and receive the draft. OSC has no authentication (EVIDENCE.md section 1) | Every client that connects. Loopback does not stop a malicious local process, and Origin checks do not replace authentication (ARCHITECTURE.md, P1 paragraph) | Same-user processes only, by file permission. **No per-client scope today:** a process that can open the socket can also call `inject` (`src/yazses/core/daemon.py:2169`) |
| **Fits which phase** | Baseline for XR-R01: does the problem exist once T0 is tried? | P0 mock demo only | P2 VRChat adapter only | P1 general bridge, and only with more than one real consumer | P1 alternative to T3 for native clients |

### What the comparison suggests (proposal for XR-R05, not a decision)

1. **Try T0 first, as evidence, not code.** If dictating into VRChat's own text field already works on a real PC client, the case for any new transport weakens sharply, and XR-R01 should ask what T0 fails to do before asking for a bridge. This needs an owner-run test on a real client; it was not done.
2. **T1 is the only option compatible with today's ADRs that needs no amendment**, and it reaches only a mock. That matches ROADMAP P0 and ARCHITECTURE.md line 41.
3. **T2 is the narrowest path to VRChat**, and its cost is governance rather than code: a third SEND under ADR-019. If ever proposed, the destination should be a hard-coded loopback literal, refusing VRChat's `--osc=` remote-IP form, by the same reasoning as `is_loopback_endpoint()` (`tests/test_egress_inventory.py:407-425`).
4. **T3 is the most expensive option** on every row: a new dependency, a listener, a browser-reachable surface, an ADR-019 amendment *and* an ADR-020 supersession. The card's own justification (several engines and WebXR) has no evidenced consumer today. It should not be the default answer to "which transport".
5. **T4 before T3 for native multi-consumer use**, but only after the IPC gains per-client scopes. Granting an XR app the socket today grants it injection and every other method.

## 3. Threat review (XR-R04)

### Assets

| Asset | Rule that already governs it |
|---|---|
| The user's own dictated text, before and after review | May leave the process only through a registered SEND (ADR-019 §1) |
| The learning corpus, voiceprints, other speakers' audio | **May never leave**, whatever the consent (ADR-019 §3, `design/adr/adr-019-egress-inventory-and-escalation.md:351-363`). The `recall` IPC method reads the corpus (`src/yazses/core/daemon.py:8101-8113`), so no XR-facing method may proxy it |
| Injection authority (typing into any focused window) | Held by the daemon; exposed over IPC as `inject` |
| Social standing in a shared world | Not ours, but every message and avatar action is seen by other people and cannot be taken back |

### Trust boundaries

- **B1, daemon to local consumer.** T1 has none (same process). T2 crosses to whoever holds port 9000, unauthenticated. T3 crosses to every connected client, including browser pages. T4 crosses to same-user processes.
- **B2, consumer to shared world.** The real external action. Once VRChat publishes a chatbox message, other participants have seen it. **No transport can make this reversible**, so the only control is that the publish is the user's own act in the host app.
- **B3, this machine to another device** (a standalone headset, a second PC). Out of scope for every option here; it is a separate, authenticated-transport design (DECISIONS.md D7).

### Threats and proposed mitigations

| # | Threat | Applies to | Proposed mitigation | Testable offline? |
|---|---|---|---|---|
| X1 | A misheard transcript is published to a world | T2, T3 | Never auto-send (policy below). VRChat's own keyboard is the confirmation | Yes, for the bytes YazSes emits; the client's behaviour only on a real client (H1) |
| X2 | Another local program binds port 9000 before VRChat and receives drafts | T2 | Send only on an explicit user action, never on a timer or event; show the destination; no background retry | Partly: the send trigger, not the binding |
| X3 | Any local process writes to VRChat's port 9000, including `b = true` | VRChat itself | **Not preventable by YazSes**; OSC has no authentication. State this in user documentation rather than imply YazSes protects it | No |
| X4 | A web page opens `ws://localhost:…` and reads transcripts | T3 | Per-client token, Origin allowlist, no unauthenticated subscriber, listener off by default. Or do not build T3 | Yes |
| X5 | An app granted IPC access calls `inject` or `recall` | T4 | Per-client method scopes before any XR use of IPC; the XR scope excludes `inject`, `recall` and anything corpus-backed | Yes |
| X6 | Revoked access keeps working | all | See revocation below | Yes |
| X7 | Duplicate or replayed send publishes twice | T2, T3 | One reviewed draft, at most one prefill; no automatic retries; a sequence number per draft | Yes |
| X8 | Text over 144 characters is truncated or split silently | T2 | Refuse or split with per-chunk confirmation (EVIDENCE.md section 2, item 2) | Yes, for YazSes's side |
| X9 | Transcripts appear in logs or crash reports | all | Log lengths and outcomes, never the text, as `sendto` already does (ADR-019, the "send to" paragraph) | Yes |
| X10 | An avatar parameter changes on a recognition guess | T2 | Allowlisted parameters only; a parameter absent from the avatar means no action; the same explicit confirmation as text | Yes, for emitted messages |

### Revocation, per transport

Revocation must take effect **before the next send**, and it cannot recall what was already published (B2).

- **T1:** unregister the callback; the next transcript reaches no consumer.
- **T2:** turning the feature off must stop the next datagram. There is no session to end. Text already sent stays in the world.
- **T3:** invalidate the token, close every open session, stop the listener when the last permission is removed.
- **T4:** today there is nothing finer than the socket's file permission, so per-client revocation **does not exist** and would have to be built with the scopes in X5.

### External-action policy (proposal)

These rules would bind any future adapter. They are written as testable statements on purpose, and per [ADR-021](../adr/adr-021-invest-in-error-cost.md) they add **no new YazSes prompt**: the confirmation is the host application's own send control, so there is no guard to learn to dismiss.

1. **YazSes never sends.** For VRChat it emits `/chatbox/input` with `b = false` only. No config key, CLI flag, voice command or IPC parameter can produce `b = true`, and a negative test checks the emitted bytes on every code path.
2. **Draft, sent and delivered are three different states**, and the user is never told "delivered" (OSC cannot confirm it).
3. **One reviewed draft, at most one prefill.** No automatic retry.
4. **Avatar actions follow the same rule as text**: allowlisted, explicit, and nothing on a guess.
5. **Off means off mid-flight**: pause or disable stops the next send, including one already queued.
6. **The destination is a loopback literal.** A remote IP, a hostname, or VRChat's `--osc=` form is refused, not honoured.
7. **Only the user's own reviewed text leaves.** Never audio, the corpus, voiceprints, recall results or another speaker's words (ADR-019 §3).
8. **The text is never logged.**

## 4. Status of the tasks this note serves

| Task | Status after this note | What is still missing |
|---|---|---|
| XR-R03 | **Partially done, not complete.** Documentation comparison recorded above | Any measured lifecycle cost; a real-client check of T0 and T2; a demand signal saying which consumers exist (XR-R01) |
| XR-R04 | **Partially done, not complete.** Threat list, revocation and external-action policy proposed above | Maintainer review; ToS/Community Guidelines check for external OSC tools (not read, per EVIDENCE.md section 6); tests can only follow an approved design |
| XR-R01 | Not started | Non-contributor demand evidence |
| XR-R05 | Not started | Needs R01 to R04 |

**ADR-030 freeze: unchanged.** No transport is chosen, no ADR is amended, and no feature-registry entry, config key or source change is proposed by this file.
