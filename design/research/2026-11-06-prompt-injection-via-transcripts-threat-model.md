# Research: prompt injection via transcripts and `ask_human` answers — re-verified threat model

**Issue:** [#803](https://github.com/MSKazemi/yazses/issues/803) (open) · **Parent:** [#788](https://github.com/MSKazemi/yazses/issues/788)  
**Date / audited revision:** 2026-11-06, `main` @ `4695e49a`  
**Status:** design input only. No runtime change, no test run against a real client, no
accepted decision. Every "proposal" below is a proposal; the companion
[proposed ADR](2026-11-03-proposed-adr-mcp-trust-and-audible-budget.md) remains **Proposed,
not accepted**.  
**Builds on:** [2026-11-03 trust-boundary audit](2026-11-03-agent-mcp-trust-boundary-audit.md)
(findings AGT-01…AGT-09), [replay spec](../specs/agent-mcp-trust-replay-protocol.md),
[ADR-019](../adr/adr-019-egress-inventory-and-escalation.md),
[ADR-020](../adr/adr-020-agent-protocols.md), [ADR-031](../adr/adr-031-send-to-prefill-handoff.md).

## Why a second note

The 2026-11-03 audit was written against `fa8159d8`. Rounds 4 and 5 have since changed the
MCP and IPC code (shared budget, stable failure text, owner-only socket, a send-to
never-submits test). This note does three things the earlier one could not:

1. re-checks each earlier finding against `4695e49a` and says which are closed;
2. narrows the scope to **text that crosses into an agent's context** — the `transcribe`
   result, the `ask_human` answer and refusal text, dictation into a focused agent, and logs;
3. separates **mitigations present in code** from **gaps**, each with `file:line`.

**Evidence rule.** `[C]` = read in source at `4695e49a`; `[T]` = an existing test asserts
it (named, not re-run for this note); `[U]` = unverified — no real MCP client, desktop
client, microphone, speaker or OS other than source reading was used. No claim here is
about how Claude Code, Codex or any other host *treats* the text it receives.

## 1. The threat in one sentence

YazSes turns sound into text and hands that text to something that may obey text. An
attacker who can put words into **audio** (a media file, a video playing in the room) or
into an **agent-supplied question** can try to get those words treated as instructions by
the downstream agent, or by YazSes's own command grammar. YazSes cannot decide how a host
treats a tool result; it *can* decide what it emits, what it reflects, and what it acts on.

## 2. Trust boundaries (text flows only)

| # | Flow | Source of the words | Who can control them | Leaves YazSes via |
|---|---|---|---|---|
| B1 | `transcribe(path)` result | any audio/video file the host names | whoever authored the file | MCP stdio reply, `src/yazses/mcp/server.py:48-58` → `src/yazses/mcp/protocol.py:355` |
| B2 | `ask_human` question | the calling agent (and anything that steered it: repo text, web pages) | the agent / indirect injector | spoken aloud, `src/yazses/mcp/ask.py:114`, `:121` |
| B3 | `ask_human` answer | the user's speech, plus any other sound in the room | user; ambient audio | IPC reply `src/yazses/core/daemon.py:9637` → MCP text `src/yazses/mcp/server.py:166-167` |
| B4 | `ask_human` refusal text | YazSes, **including exception text** | YazSes internals (paths, model errors) | `src/yazses/mcp/ask.py:128` → `src/yazses/core/daemon.py:9641` → `src/yazses/mcp/server.py:168-170` |
| B5 | Hold-to-talk dictation into a focused agent (terminal, chat box) | user's speech, plus ambient audio during the hold | user; ambient audio | keystrokes; voice commands such as `press enter` |
| B6 | Send-to hand-off | dictated text | user | custom-scheme URL, `src/yazses/sendto/targets.py` / `handoff.py` |
| B7 | Logs | dictated text at DEBUG | — (disclosure, not injection) | `daemon.log`, user-shared reports |

All of B1, B3 and B4 reach the host as one undifferentiated `{"type":"text"}` content item
(`src/yazses/mcp/protocol.py:230-234`). Nothing in the payload marks *who said it*.

## 3. Mitigations already in code

| ID | Mitigation | Anchor | Evidence |
|---|---|---|---|
| M1 | Stdio only, no port; the server is a child of its host | `src/yazses/mcp/server.py:8-12` | [C] |
| M2 | Tool exceptions never reach the wire verbatim: fixed text per failure class, full exception to stderr only | `src/yazses/mcp/protocol.py:67-83`, `:171-185`, `:345-354` | [C] [T] `tests/test_mcp_protocol.py:395`, `:456`, `:480`, `:490` |
| M3 | Caller-supplied argument names and tool names are not reflected in errors | `src/yazses/mcp/protocol.py:305-316`, `:188-227` | [C] [T] `tests/test_mcp_protocol.py:369` |
| M4 | Speech-model error lines repeated only when short and path-free | `src/yazses/mcp/protocol.py:100-121` | [C] [T] `tests/test_mcp_protocol.py:456` |
| M5 | Internal errors in the loop answer with fixed `Internal error.`; nothing from the frame echoed | `src/yazses/mcp/server.py:261-274` | [C] |
| M6 | `ask_human` is off by default and not even listed when off | `src/yazses/config.py:1854`, `src/yazses/mcp/server.py:209-211` | [C] [T] `tests/test_ask_human.py:79` |
| M7 | One daemon-lifetime interrupt budget with atomic reserve/commit/release (closes earlier **AGT-01**) | `src/yazses/core/daemon.py:547`, `:9617-9622`; `src/yazses/mcp/ask.py:104-111`, `:118-144` | [C] [T] `tests/test_ask_human.py:407`, `tests/test_ask_human_concurrency.py:73`, `:144` |
| M8 | Never asked during a hold | `src/yazses/core/daemon.py:9633`, `src/yazses/mcp/ask.py:107` | [C] [T] `tests/test_ask_human.py:88` |
| M9 | The answer is **never typed**: the listener bypasses `_on_hold_end`, and the service holds a deliberately-unset injector | `src/yazses/core/daemon.py:9666-9723`, `src/yazses/mcp/ask.py:82-85` | [C] [T] `tests/test_ask_human.py:147` |
| M10 | The answer is **not run through the command grammar**: the listener returns `engine.transcribe(audio)` directly, so a spoken answer cannot dispatch a voice command | `src/yazses/core/daemon.py:9723` | [C] |
| M11 | No-speech answers are never decoded, so Whisper cannot hand back primed prompt words as an "answer" (#598 shape) | `src/yazses/core/daemon.py:9717-9720` | [C] |
| M12 | Listening is capped at 120 s whatever the caller asks | `src/yazses/mcp/ask.py:60`, `:116` | [C] [T] `tests/test_ask_human.py:157` |
| M13 | IPC socket is owner-only (0o600), so only the same OS user can claim a `caller` | `src/yazses/ipc/server.py:74-87` | [C] |
| M14 | Send-to emits one inert, percent-encoded URL; the package cannot synthesize Enter | `src/yazses/sendto/targets.py:55-73` | [C] [T] `tests/test_send_to_never_submits.py:46`, `:68`, `:131`, `:145` — real-client behaviour **[U]** (ADR-031 §5) |
| M15 | Destructive shell commands can be held for spoken confirmation (`[cmdsafety]`, **off by default**) | `src/yazses/config.py:1658-1682` | [C] |
| M16 | Transcript text logged only at DEBUG; INFO carries counts | `src/yazses/core/daemon.py:4634`, `:4588`; report handling `src/yazses/system/report.py:464-491` | [C] [T] `tests/test_log_privacy_claims_name_the_condition.py` |
| M17 | No transcript "sanitizer": the user's words are not rewritten by a heuristic injection filter (a deliberate non-mitigation, proposed-ADR D5) | — | design position, not code |

## 4. Gaps (each a code-path observation, not a reproduced exploit)

| ID | Gap | Anchor | Why it matters here | Severity (judgement) |
|---|---|---|---|---|
| **G1** | **Exception text bypasses M2 on the `ask_human` path.** `Refusal(f"The question could not be asked: {exc}")` embeds the raw exception message; the daemon returns it as `reason`; the MCP tool returns `reason` as ordinary (non-`isError`) text, so `protocol.py`'s stable-message filter never sees it. The listener calls `engine.transcribe(audio)` without a guard (`daemon.py:9723`), and speech-model errors carry the model cache directory in their body (per the comment at `protocol.py:127-129`). | `src/yazses/mcp/ask.py:123-128`; `src/yazses/core/daemon.py:9638-9644`; `src/yazses/mcp/server.py:168-170` | Contradicts the "no path echo" property M2 establishes for every other tool failure; a local path or internal detail lands in the host's (possibly cloud) context. Not reproduced. | Medium |
| **G2** | **No provenance marker on returned text.** Transcript, answer and refusal text are all bare `text` content; nothing says "words heard from audio" vs "YazSes status". | `src/yazses/mcp/protocol.py:230-234`, `:355` | A host that wants to fence untrusted tool output has nothing to key on beyond the tool name. Hosts may ignore any marker; this is advisory only. | Low–Medium |
| **G3** | **No tool annotations or server `instructions`.** `initialize` returns `capabilities: {"tools": {}}`; `tools/list` returns name/description/schema only (no `openWorldHint`, `readOnlyHint`, `title`). | `src/yazses/mcp/protocol.py:291`, `:296-298` | `transcribe` is read-only over local files but its output is open-world content. MCP itself says annotations are hints, not controls. | Low |
| **G4** | **`caller` is unauthenticated.** The MCP server always sends `"mcp"`, but the daemon accepts any string any same-user IPC client sends and speaks it verbatim ("`<caller>` asks: …"). | `src/yazses/mcp/server.py:150`; `src/yazses/core/daemon.py:9614`; `src/yazses/mcp/ask.py:114` | Earlier **AGT-03** still open. A same-user process can make a question sound like it comes from a trusted name — voice social engineering toward an "answer" the attacker then reads. Bounded by M13. | Medium |
| **G5** | **Question length unbounded; question spoken verbatim.** No `maxLength` in the schema; the service strips but does not bound. | `src/yazses/mcp/server.py:183`; `src/yazses/mcp/ask.py:99`, `:114` | Earlier **AGT-09** still open. A long, urgent script read aloud is the voice form of prompt injection aimed at the human. Accessible-use limits unmeasured, so no number is proposed. | Low–Medium |
| **G6** | **Kokoro swallows playback errors.** `speak()` catches any exception, logs at DEBUG and returns normally, so `ask.py`'s "unheard question is not charged" branch (`:123-128`) never fires for it; a partly-spoken question proceeds to listening. | `src/yazses/tts/kokoro.py:128-143` | The human may answer a question they heard only half of; the agent receives that answer as if to the full question. Not reproduced. | Low–Medium |
| **G7** | **Ambient audio can carry a voice command into a focused agent.** `press enter` / `return` / `new line` map to Return; `[commands]` is on by default. During a hold, sound from a speaker in the room is transcribed like the user's voice. | `src/yazses/commands/grammars/en.py:77-78`; `src/yazses/commands/dispatch.py:29`; `src/yazses/config.py:485` | In a focused agent terminal, Return submits what was typed. Requires an active physical hold (hands-free modes are off by default), which bounds it sharply. Rate unmeasured. | Low |
| **G8** | **No control-character filter located before keystroke injection.** A grep of `inject/`, `postprocess/` and the daemon found only a bidi-control strip for Persian. Whether any supported decoder emits `\n`/control bytes, and whether a backend types `\n` as Return, was **not** checked. | `src/yazses/postprocess/persian_text.py:58`, `:140-148` (the only hit) | If both held, dictated text could submit itself in a terminal agent. Entirely **[U]**; the fuzz harness (`fuzz/`) is the right place to look first. | Unknown |
| **G9** | **Diarized `transcribe` output is `speaker: text` with no escaping.** Transcript words that themselves read like `SPEAKER_01: …` are indistinguishable from a real label. | `src/yazses/mcp/server.py:50-54` | Speaker-attribution spoofing in meeting transcripts handed to an agent. Requires the decoder to emit such text. | Low |
| **G10** | **`notifications/cancelled` is dropped and the stdio loop is sequential.** A host cannot cancel a blocking `ask_human`, and no other request is served meanwhile. | `src/yazses/mcp/protocol.py:269-270`; `src/yazses/mcp/server.py:228-277` | Availability, not injection: an injected agent that calls `ask_human` holds the microphone up to M12's cap and the server for that long. | Low |
| **G11** | **ADR-019 has no row for MCP stdio results.** Its hand-off section lists `system/browser.py` and `sendto/handoff.py`; `transcribe` results and `ask_human` answers are written to the host's pipe but are not inventoried. | `design/adr/adr-019-egress-inventory-and-escalation.md:166-176` (grep for `mcp`/`stdio`/`ask_human` finds nothing) | "Offline recognition ≠ offline consumption" is stated in the 2026-11-03 audit but not in the accepted inventory. | Documentation |

Earlier finding **AGT-02** (unanswered questions are not charged) is now **intended
behaviour** — `ask.py:130-144` releases the slot and `tests/test_ask_human_concurrency.py:115`
asserts it. Whether that is the right accounting is the open decision in the proposed ADR,
not a defect.

## 5. Proposals (not decisions)

Ordered by value per unit of risk. Each would be its own change with its own tests;
nothing here changes a public interface unless stated, and those need a maintainer.

1. **G1 — route `ask_human` failure text through the same classifier as tool failures.**
   Smallest form: `ask.py:128` uses a fixed message (or `protocol._failure_text`-style
   classification) and logs the exception to stderr. Test: a fake listener raising an
   exception whose message carries a synthetic path sentinel; assert the sentinel is absent
   from the IPC `reason` and from the MCP tool text. No interface change.
2. **G11 — propose an ADR-019 amendment row** for "returned to the MCP host over stdio":
   payload = transcript / spoken answer; destination = the host process; YazSes transmits
   nothing further. Needs maintainer acceptance; this note does not amend the ADR.
3. **G4 — speak a fixed, honest requester label** ("an MCP client") unless and until a
   caller identity can be authenticated; keep the IPC `caller` param for logs only. This
   changes spoken behaviour of an IPC method → L3, maintainer decision.
4. **G6 — make the TTS contract observable**: `speak()` signals an interrupted playback
   (return value or raise) so `ask.py` can refuse instead of listening. Test with a fake
   backend; real-speaker behaviour **[U]**.
5. **G2/G3 — advisory metadata**: `annotations` (`readOnlyHint: true`, `openWorldHint: true`
   on `transcribe`), and a one-line server `instructions` stating that tool results are the
   words heard, not instructions. Purely advisory per MCP; must not be presented as a
   control. Changes `tools/list` output → maintainer.
6. **G8 — measure before acting**: a fuzz/property target asserting what the injector
   receives for decoder output containing `\n`, `\r`, `\x1b`. Only if a real path exists,
   propose a filter; a filter that alters legitimate multi-line dictation would itself be a
   regression.
7. **G5, G7, G9, G10 — research only.** Each needs a measurement (TTS length vs. accessible
   use; false-command rate from ambient audio during holds; decoder output containing
   label-like text; whether real hosts send `notifications/cancelled`) before any change.
   G7 overlaps the unintended-activation note
   ([2026-11-05](2026-11-05-emergency-stop-and-unintended-activation-threat-model.md)).

**Explicit non-proposals:** no heuristic "prompt-injection detector" that rewrites or drops
the user's words; no network path; no claim that YazSes can make a host treat output as
data. These stand from the 2026-11-03 audit (§4 "No-go").

## 6. What would change this assessment

- A synthetic reproduction of G1 (expected to be easy; see proposal 1).
- Real-client evidence (version × OS) of how hosts render `isError`, annotations or
  `instructions` — tracked with handoff/compatibility work, not here.
- A measured false-command rate from ambient audio during holds (G7).

## References

- [OWASP Top 10 for LLM Applications — LLM01: Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) — segregate untrusted content, least privilege, human approval for high-risk actions. [F]
- [MCP specification 2025-06-18 — Tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) — the revision this server speaks; tool results, `isError`, annotations as untrusted hints. [F]
- [MCP blog — tool annotations (2026-03-16)](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/) — annotations are advisory, not enforceable. [F]
