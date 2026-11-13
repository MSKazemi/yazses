# ADR-v2-156 — A wired text link from a MaixCAM2 board: research record, out-of-tree example, no product feature

**Status:** Proposed (2026-11-13); requires a maintainer decision (see [Decision requested](#decision-requested)) before anything beyond the out-of-tree example exists
**Scope:** Whether a separate board that recognises speech on-device may send **already-recognised text** or a **trigger** to a YazSes desktop over a wired UART. **Not** a new YazSes capability, not a claim that any board works, not an authorisation to change `src/`
**Related:** [ADR-030](adr-030-agent-era-direction.md) (breadth freeze), [ADR-019](adr-019-egress-inventory-and-escalation.md) (egress inventory), [ADR-021](adr-021-invest-in-error-cost.md) (investment follows evidence), [ADR-v2-148](adr-v2-148-hands-free-composition.md) (one global safety state), [ADR-v2-155](adr-v2-155-thinkgear-transport-safety.md) (the closest precedent: a Proposed ADR for a serial device), [roadmap: how a research idea earns implementation](../../docs/roadmap.md#how-a-research-idea-earns-implementation)
**Companion artefacts (written alongside this ADR, not inside it):** the normative wire format `design/specs/textlink-wire-protocol.md`; the device-free reference code `examples/maixcam2-text-link/`; the user-facing notice [`docs/research/maixcam2-text-link.md`](../../docs/research/maixcam2-text-link.md)

Evidence labels used throughout: **[V]** verified, with the source named · **[U]** unverified · **[O]** engineering judgement. A claim without a label does not appear in this record.

---

## Context and problem

A Sipeed MaixCAM2 board can run Whisper `base` on the board itself. The owner asked the vendor whether such a board could send locally recognised text, or a trigger, to a YazSes desktop over a wired serial link, so that the speech-to-text work happens on a second, small, dedicated device and the desktop receives plain text.

What is known:

| Fact | Label | Source |
|---|---|---|
| MaixCAM2 supports Whisper `base` for Chinese and English; the model table lists 1 GB of memory | **[V]** | Sipeed MaixPy documentation, <https://wiki.sipeed.com/maixpy/doc/en/mllm/asr_whisper.html>, fetched 2026-11-13 |
| The model has to be downloaded (the page links a `whisper-base-maixcam2` model on Hugging Face) | **[V]** | same page |
| The Whisper page says nothing about whether the board needs the internet at run time or any activation step | **[V]** that it is silent; **[U]** what the answer is | same page |
| "The first setup needs internet access to activate the device, install the runtime, and connect development tools." So any "offline" property can hold **only after a one-time online setup** | **[V]** | MaixPy `docs/doc/en/README_MaixCAM2.md`, "Connect to the Network" (line 47 as reported by the coordinator; the line number was not independently confirmed, the sentence was re-read in the raw file on 2026-11-13), <https://raw.githubusercontent.com/sipeed/MaixPy/main/docs/doc/en/README_MaixCAM2.md> |
| The board's USB cable makes it appear on the computer as a **USB network adapter** (NCM and RNDIS drivers; the device at `10.131.167.1`, the host adapter on the same subnet), **not** a serial port; for serial the vendor says to supply a USB-to-serial module | **[V]** | same README, "Preparing to Connect Computer and Device", method 2 (lines about 101 to 115 as reported; text re-read 2026-11-13) |
| Neither source says whether Whisper recognition itself, as opposed to setup, activation and model download, makes any network call; the vendor's emails say Whisper runs locally but did not separate those phases | **[V]** that this is unanswered; **[U]** the answer | both pages and the email thread |
| The vendor replied by email (2026-11-03 to 2026-11-09) that a UART link is feasible, that examples are in the MaixPy repository under `examples/peripheral/uart`, that UART0 is the console and should be left unused, that the board's USB port is a USB *function* port and **not** a serial bridge so a USB-to-UART adapter on the UART pins is required, and that Whisper runs locally | **[V]** as a vendor statement in the owner's mailbox; **[U]** as a measured fact, because no board has run any of it |
| The vendor did **not** answer in the thread whether first-time model download or device activation needs the internet (the README above now says the first setup does) | **[V]** (absence of an answer in the thread) | same thread |
| No board is owned, nobody has offered to lend one, and no user has asked for this | **[V]** that none is recorded; **[U]** for demand that never reached the tracker | the owner's records and the repository's issue tracker as of 2026-11-13 |
| YazSes already reads a serial device in one place: the opt-in EMG sensor over `[emg] device_port` using `pyserial` (the YESP protocol) | **[V]** `design/emg-protocol.md`; `pyproject.toml` lists `pyserial>=3.5` |

The question is therefore not "can it be built" (it can; the framing is small and a reader is a few dozen lines) but "should the YazSes project own any of it, now, with zero evidence of demand and no hardware".

## Hypothesis (falsifiable)

> **H1.** A MaixCAM2 running Whisper `base` and a USB-to-UART adapter, connected to a Linux desktop running a receive-only reader of the framing in `design/specs/textlink-wire-protocol.md`, will (a) deliver recognised text frames with no frame accepted that fails CRC or UTF-8 validation, (b) recognise speech **after the one-time online setup** with the board's network interface disabled, and (c) do so with an end-of-speech-to-text-on-host latency and word-error rate that a named person considers usable for dictation into an agent prompt.

H1 is false, and the idea stops, if **any** of the following is observed on a named board, firmware and model version:

- **F1.** Recognition needs a network connection after the one-time online setup and model download (offline-after-setup fails). The setup itself is known to need the internet **[V]**; only what happens afterwards is in question.
- **F2.** The board cannot emit on a header UART that a USB-to-UART adapter can read at a rate the framing needs, using only the vendor's documented API.
- **F3.** The measured WER or latency is worse than the YazSes desktop path on the same speech by more than the person who would use it will accept (the threshold is chosen by that person *before* measuring, not after).
- **F4.** Any frame that violates the wire spec is accepted by the reference reader (a conformance failure, which is a bug in the reader, not in the idea, and is fixed before anything else is concluded).

H1(c) deliberately has no number. A number here would be invented; the threshold belongs to a human user at measurement time.

## Why now, and why not now

**Why now (the case for writing it down):**

- The owner holds a vendor answer that is time-sensitive in the sense that it is easy to lose; recording it costs one document. **[O]**
- A *device-free* reference reader and frame codec can be built and tested entirely from synthetic bytes, and prove the parser rejects hostile input, with no hardware and no change to `src/`. **[O]**
- ADR-030 §3 explicitly provides for this: "A proposal outside the pillars during the freeze is written down as a *Proposed* ADR or an `evergreen:research` issue and stops there." **[V]** `adr-030-agent-era-direction.md`, §3.

**Why not now (the case against building it into YazSes):**

- **The breadth freeze is in force.** A second input device family is outside the four pillars of ADR-030 §2. Lifting or excepting the freeze is a maintainer decision recorded as an amendment, as the 2026-11-01 amendment did for the biosignal pipeline. **[V]** ADR-030 §3 and Amendment 2026-11-01.
- **No demand evidence.** ADR-030's leading signal is "a substantive issue or discussion from someone who is not a contributor". There is none for this. ADR-021: "Investment follows evidence." **[V]**
- **No device.** Every property that matters (offline-after-setup, latency, WER, behaviour of the pins, threading in the callback) is unmeasured; see [Unknowns](#unknown-until-a-board-exists). A design reviewed without a device would be the same failure ADR-v2-155 was written to avoid. **[V]** (no board in the owner's possession).
- **It adds an untrusted text source to a program that types.** That is the highest-consequence part of the system. A reference reader in `examples/` does not touch it; a product feature would.
- **The user already has the thing the board provides.** YazSes transcribes locally on the desktop CPU. The marginal user value of moving ASR to a separate board is unestablished. **[O]**

## Decision (proposed)

1. **Record this research question and stop at the roadmap gate.** Status stays Proposed. No `src/` change, no config key, no CLI command, no IPC method, no registry capability, no extra in `pyproject.toml`.
2. **Ship only an out-of-tree reference example** under `examples/maixcam2-text-link/` (Option B): a pure frame encoder/decoder, a **receive-only** reader that **prints** accepted frames and never types, never calls the injector, never opens a network socket, and a synthetic-byte test corpus. Whether that folder carries its own tests is decided by the example's author within the repository's test rules; this ADR does not add or move any test.
3. **Do not implement Option C (a `[textlink]` product feature) unless the maintainer both records a go and grants a named freeze exception**, and then only under the constraints in [Requirements on any future product wiring](#requirements-on-any-future-product-wiring).
4. **Do not use Option D (HTTP/LAN or USB-network transport) for the first test, and do not implement it in YazSes.** The UART path with a USB-to-UART adapter is the chosen first test. See the egress statement.
5. **File one `evergreen:research` issue** carrying the hypothesis and falsifiers above, so a person who owns a board can run the measurement. The draft is kept private until the maintainer approves filing.

## Options considered

| Option | Description | Upside | Downside | Verdict |
|---|---|---|---|---|
| **A. Park** | Write nothing; keep the vendor email | Zero maintenance, zero risk | Loses the threat analysis and the answer from the vendor; nobody with a board can pick it up | Acceptable fallback; **not recommended** over B because B costs almost nothing and is reversible |
| **B. Out-of-tree example only** | Spec + pure reference codec + receive-only printing reader under `examples/`; research issue; this ADR | Reviewable, no device needed, no new surface in `src/`, no dependency added to the product, deletable in one commit | Someone has to *want* it for it to matter; a spec with no second implementation can be wrong in ways nobody has noticed | **Recommended. Chosen for the example.** |
| **C. Product feature behind opt-in `[textlink]`** | A reader inside the daemon that feeds recognised text into the dictation pipeline, off by default | The only option that makes the feature usable by a non-developer | Violates the freeze unless excepted; adds an untrusted text source in front of an injector; unverifiable without a board; maintenance for a device nobody owns | **Rejected for now.** Re-open only on the [exit criteria](#exit-and-kill-criteria) |
| **D. HTTP/LAN or USB-network transport** | The board sends text to a TCP/HTTP port on the desktop, either over the LAN (if it has Wi-Fi **[U]**) or over its USB cable, on which it already appears as a USB network adapter (NCM/RNDIS, `10.131.167.1`) **[V]** | No USB-to-UART adapter needed for the USB variant | Adds a listening socket to a project whose property is that nothing leaves (and nothing enters) the machine; ADR-019 treats a non-loopback bind as the exact one-word diff to guard against. **The USB variant is not internet egress**: the link is local, and the first test rejects it for a narrower reason, namely that it adds a **socket surface** on the desktop and puts the board on a network interface of the host, so a bind that is meant for the USB adapter can also be reachable from every other interface unless it is pinned to that address, and the board's own software then has an IP path to the host. The LAN variant additionally adds a path from other machines | **Rejected for the first test**, on those grounds, not because it is impossible. A USB-network transport is the natural no-adapter alternative and can be re-examined, with its own threat model, if the UART path fails F2 |

**Recommendation:** accept this ADR as a *research record* (the first of the three choices in [Decision requested](#decision-requested)), adopt Option B for the example, keep C closed.

## Threat model for text arriving over a wire

The trust boundary is the cable. Everything arriving on it is **untrusted input**, even from a board the user owns and flashed. The mitigations below are split into what the **out-of-tree example** does (verifiable by its own tests, from synthetic bytes) and what a **future product wiring must do** (nothing of which is implemented or tested today).

| # | Threat | How it arises | Mitigation | Where enforced | Residual risk |
|---|---|---|---|---|---|
| T1 | **Keystroke / command injection** | Text from the device is typed into the focused window; in a terminal a line of text is a shell command, and a newline or a control character is an Enter or an escape sequence | The example **never types**: it prints. The wire spec refuses control characters and bidi controls in text, so no frame can carry a newline, escape or tab. Any product wiring **must** hand the text to the *same* path dictated text takes, never to the injector directly, so the existing command-safety classifier (`src/yazses/cmdsafety/`, ADR-v2-065) and the no-text-target guard in `core/daemon.py` apply; it **must** support staged mode (review before commit); it **must** never synthesise Enter, and **must not** append a trailing newline | Example: parser + printing. Product: existing guards, **untested for this source** | A confusable or plausible-looking command that is not on the classifier's list will still be typed. The classifier is pattern-based **[V]** (`cmdsafety/classify.py`), not a proof |
| T2 | **Hostile or spoofed device / cable** | Anything that can write to the serial port can produce any frame; the framing has a CRC, which detects corruption and is **not** authentication | The port is **named explicitly by the human**; no auto-discovery or scanning of serial ports (probing unknown devices can disturb them). The reader is receive-only by default. State plainly that v1 has **no authentication**: physical access to the cable is the trust boundary | Example: reader takes a path argument; nothing scans. Product: config key naming one port | Anyone with physical access to the wire, or malware able to write to the port, can inject. Not solved by CRC; would need a shared-secret MAC, which is out of scope for v1 **[O]** |
| T3 | **Replay** | A captured valid frame is sent again | `SEQ` (u8) lets the reader drop duplicates and report gaps within its window. A bounded rate limit makes replay-at-speed ineffective | Example: reader. Product: same, plus staged mode | `SEQ` wraps at 256 and is unauthenticated, so a *replay after a wrap* or a forged `SEQ` is indistinguishable from a real frame. This is a stated limitation, not a defect to be hidden |
| T4 | **Flooding / resource exhaustion** | A device (or noise on a floating pin) streams garbage or a stream of valid tiny frames | `LEN` is `u16`, so the parser **must** reject any `LEN` above the text maximum (512 bytes) **before** buffering; bounded buffer; resynchronise on `SYNC` after any error; per-second frame cap that **drops** rather than queues. Product wiring must not let a flood delay dictation or the hold-to-talk release path | Example: parser (tested with oversized and endless input). Product: bounded queue, drop-newest | The cap is a policy number chosen by the implementer; this ADR does not supply one |
| T5 | **Unicode confusables and bidi tricks** | Text containing right-to-left overrides, isolates, zero-width characters or look-alike letters that reads differently from what is typed | Strict UTF-8 decode (reject, never "replace"); refuse control and bidi characters (spec). **Do not reuse `src/yazses/bidi.py`**: it builds *display* strings and is deliberately never on an injection path (its own header, enforced by `tests/test_bidi.py`) | Example: validator | Look-alike letters from permitted scripts (a Cyrillic `а` in a command) pass any control-character filter. A future wiring may add a per-script allowlist; that is not designed here |
| T6 | **A device that lies about being offline** | The board's Whisper run might call a remote service, or its setup might phone home; its own network stack is outside YazSes | YazSes **cannot verify** what the board does. The documentation says "offline" only for what is verified, and currently nothing about the board is. Setup itself is documented to need the internet **[V]**, so "offline" can at most mean *after* a one-time online setup. The research measurement for F1 is: complete setup, **disable the board's network interface**, then confirm recognition still works, and observe the board's traffic from outside it (router or a capture on the upstream side). The ADR-019 statement covers the *host* only | Measurement protocol in the research issue | Until F1 is measured, "offline" for the board is **[U]**. A user's speech is captured and processed on a computer YazSes does not control |
| T7 | **Supply chain of the board image** | Vendor firmware, MaixPy, and the Hugging Face model are third-party code and weights that run on the board | YazSes ships, downloads and signs **none** of them (verified by the ADR changing nothing in `src/`). The host treats the device as untrusted *regardless* of provenance, so a compromised image still cannot exceed what a hostile device can do in T1 to T5. Document the exact firmware and model versions used in any measurement | Design principle: no trust in the device | A malicious image is inside the board's trust domain; YazSes cannot attest it |
| T8 | **Recognition errors typed as if said** | Whisper-family models are known to emit plausible text for non-speech audio or noise; nothing on the wire distinguishes it from real speech | Staged mode for any product wiring; the example prints. A `TRIGGER` frame must not start an action that cannot be reviewed first | Product only | Rate and shape of hallucination on this board are **[U]** (see Unknowns) |
| T9 | **A trigger that does more than a switch can** | A `TRIGGER` frame mapped to "do something" becomes remote action | A trigger may invoke only an intent that an existing hands-free switch can already invoke, subject to the same global pause and stop of ADR-v2-148; never "send", never Enter, never a shell command | Product only | None added if the rule is kept |

### Requirements on any future product wiring

If a maintainer ever grants a freeze exception for Option C, the PR **must** satisfy all of the following, and a reviewer should reject it if any is missing. None of this is implemented.

1. **Off by default.** A `[textlink]` section with `enabled = False`; an existing install is unchanged (AGENTS.md rule 2).
2. **No new network primitive.** The module must not import `socket`, an HTTP client or anything in `tests/test_egress_inventory.py`'s network roots.
3. **Route through the existing guards**: command safety (ADR-v2-065) and the no-text-target guard; staged mode honoured; global pause and stop honoured.
4. **No trailing Enter, no control characters, no direct call to the injector.**
5. **Heavy or optional dependencies lazily imported** inside the function that needs them; `pyserial` is already a dependency (AGENTS.md rule 3).
6. **Pure logic separate from the port**: the frame parser is a dependency-free module tested directly; the serial reader is the injected backend (AGENTS.md rule 5; compare `meeting/segmenter.py`).
7. **Tests with the change**, including the hostile-input cases of T1 to T5 (AGENTS.md rule 7).
8. **A guard is judged on how rarely it fires** (AGENTS.md rule 9; ADR-021). The *refusals* above (oversized frame, bad CRC, control character) fire only on a specific, checkable signal, and a refusal must not interrupt the user; log and count it. Do not add a heuristic that fires on ordinary speech.
9. **Regenerate generated files**: `scripts/gen-docs.py` for the new config section, CLI or registry entry; `scripts/gen-adr-index.py` for ADR changes.
10. **Egress inventory updated** as stated below.

## Egress statement

- **A wired UART adds no outbound network path from the host.** A serial port is not a network. The existing precedent is that ADR-019 records local-but-not-AF_UNIX modules (`platform/emg/ble_backend.py`, `biosignal/myo.py`) under `LOCAL_BOUND` in `tests/test_egress_inventory.py` rather than excluding them. **[V]** `tests/test_egress_inventory.py` lines 71 to 88 on this branch. This ADR changes **no** module, so ADR-019's inventory and its count of paths that can transmit what the user said (two) are unchanged.
- **If Option C is ever implemented**, the change to the egress inventory would be: add the new reader module to `LOCAL_BOUND` with a one-line reason ("reads a serial port the user named; no socket; a cable is not an IP network") and a test that reads its source and asserts it imports no network root, mirroring `test_the_ble_backend_opens_no_socket`. That is a *recorded exception that is pinned by a test*, not an ADR-019 escalation, because nothing leaves the machine. It would be a test change in a separate PR, not part of this one.
- **Option D is declined for the first test.** An HTTP/TCP listener on a LAN interface would add an inbound path from other machines, and ADR-019 identifies a non-loopback bind as "a one-word diff" that puts a text-injection port on the LAN (`remote/agent.py` row). The USB-network variant (the board appears as a USB network adapter, NCM/RNDIS **[V]**) is a local link and **not** internet egress, so it would not change the count of paths that can send what the user said; it is declined for a narrower, stated reason: it adds a listening socket on the desktop and places the board on a host network interface, so the bind address must be pinned to that adapter and the board gains an IP path to the host. A UART has neither property. If it is ever revisited it needs its own `LOCAL_BOUND` row, a test that pins the bind address, and its own threat model.
- **The board is outside this boundary.** What the board itself transmits (model download, activation, any telemetry in its image) is not covered by ADR-019 and is **[U]** until measured (T6).
- **AGENTS.md rule 1** ("Nothing leaves the machine") is not engaged by this ADR because it adds no code that sends. **AGENTS.md "Account, permission, and cost safety"** applies to the measurement: real voice recordings, transcripts and voiceprints are never uploaded to a third-party coding agent; use synthetic or de-identified fixtures only.

## AGENTS.md rule checklist

| # | Rule | Status for this ADR |
|---|---|---|
| 1 | Nothing leaves the machine | Not engaged: no code that sends. Option D rejected for the first test (LAN: new inbound path; USB-network: new socket surface) |
| 2 | New features ship off by default | N/A to the example (not a feature). **Required** of any Option C: `[textlink] enabled = False` |
| 3 | Heavy dependencies are optional extras, lazily imported | No dependency added. A future reader reuses `pyserial`, already declared **[V]** `pyproject.toml` |
| 4 | Latest stable version with a `>=` floor | No new dependency |
| 5 | Pure logic pure | The codec is dependency-free and separate from the port (example today; mandatory for Option C) |
| 6 | Platform code behind Protocols | The serial port is not an OS seam in the Protocols of `platform/base.py`; a future reader would follow the existing EMG serial pattern. Not decided here **[O]** |
| 7 | Tests come with the change | Required of the example (synthetic bytes) and of any Option C PR |
| 8 | No AI authorship or contributor credit | Observed in this branch |
| 9 | A guard is judged on how rarely it fires | Refusals are on checkable signals only and are logged, not interrupting (T1, T4, T5; requirement 8) |
| 10 | Cite the landing page, not the file | The Sipeed source above is the documentation page |
| 11 | Private tiers stay private | Nothing here references a private tree |

## Unknown until a board exists

None of the following has been measured. None may be stated as true in any document, issue or release note until it is.

1. **Offline after setup** (F1): the first setup needs the internet **[V]**; whether recognition makes any network call *afterwards*, and whether model download is part of that setup or later, is not known. The vendor's emails say Whisper runs locally but did not separate activation and download from inference; the Whisper wiki page is silent.
2. **End-to-end latency**: from end of speech to text arriving on the host.
3. **WER**: on the board's `whisper-base-maixcam2` build, for English and for Chinese, against the YazSes desktop path on identical audio.
4. **Hallucination on silence or noise**, and whether the board applies a VAD or energy gate.
5. **Pin map and electrical behaviour**: which header pins are UART TX/RX on the specific revision, the logic level (the adapter must match it), whether a pin map or function-enable step is required before the UART is usable, and whether UART0 really can be left alone.
6. **Callback threading** in the MaixPy ASR and UART APIs: whether recognition callbacks and UART writes may run on different threads and whether a blocking write can stall recognition.
7. **Sustained thermal and memory behaviour** with the 1 GB model resident next to anything else the board runs.
8. **Behaviour when the cable is unplugged or the host is not reading** (back-pressure, dropped frames).
9. **Demand**: whether any person other than the owner wants this.

## Consequences and explicit trade-offs

- **Positive.** The vendor answer and a hostile-input threat analysis are preserved; a person who owns a board can run the measurement from the issue; nothing in `src/`, the default install or the egress inventory changes.
- **Negative.** A reference reader without a second implementation or a device can encode misunderstandings that tests built by the same author will not catch (a conformance risk). A spec that nobody uses is maintenance on the documentation site.
- **Neutral.** If H1 fails on F1, the example and ADR are removed or marked Rejected; nothing downstream depends on them.

## Exit and kill criteria

**Stop and mark this ADR Rejected (and remove the example and the docs page in one commit) if any of:**

- F1, F2 or F3 above is observed on a named board and version.
- 90 days after acceptance as a research record (2027-02-11, if accepted on 2026-11-13) pass with **no** board available to anyone willing to run the measurement **and** no non-contributor issue or discussion asking for this. Absence of both is itself the answer.
- The maintainer records a no-go at the roadmap gate.
- A security review finds a hostile-input case the reader accepts that cannot be fixed in the parser.

**Re-open for Option C only if all of:** a person other than the owner reports a need in a substantive issue; a board and the measurement have produced a recorded result for F1 to F3 that passed; and the maintainer records a go **and** grants a named freeze exception under ADR-030 §3 (as the 2026-11-01 amendment did for biosignal).

## Decision requested

The maintainer is asked to choose **one**:

1. **Accept as a research record (recommended).** This ADR stays Proposed or becomes Accepted *as a record only*; the out-of-tree example and the docs page stay; the `evergreen:research` issue may be filed; **no** implementation is authorised.
2. **Grant a named freeze exception** for Option C. The exception must name the owner of the work, state that the hands-free and agent-era pillars of ADR-030 are not displaced, require every item in [Requirements on any future product wiring](#requirements-on-any-future-product-wiring), and be recorded as an amendment to ADR-030 in the style of the 2026-11-01 amendment. **Not recommended**: no demand evidence, no device.
3. **Reject.** The example, the docs page and this ADR are removed (or the ADR is marked Rejected and kept as a record of the reasoning); the vendor reply stays in the owner's records.

**Verification status:** Design, documentation and source reading only. The Sipeed page was fetched on 2026-11-13; the vendor email is the owner's report of the thread. No board, firmware, adapter, serial capture or test was involved in writing this ADR.
