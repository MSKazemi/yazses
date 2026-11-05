# YazSes XR — evidence log: platform audit (XR-R02)

**Status: RESEARCH RECORD, 2026-11-05. Documentation only.** Nothing here was tested on any headset, any VRChat client, any avatar or any XR runtime. No YazSes XR adapter, bridge or demo exists, and nothing below is a compatibility claim. This file does not lift the [ADR-030](../adr/adr-030-agent-era-direction.md) freeze. It is the evidence behind task XR-R02 in [TASKS.md](TASKS.md), and it covers only that task. Demand (XR-R01), transport comparison (XR-R03), the threat review (XR-R04) and the decision memo (XR-R05) are still undone.

**Method.** Public primary sources only (vendor and standards-body pages), each fetched on 2026-11-05 through a page-to-text tool. The "last updated" values for VRChat pages are the page front matter as reported by that tool, not a date printed on the page. "Not read in full" means a part of the source was not seen, so an "absent" finding is weaker there.

## 1. Primary-source table

| Source | URL | Read | What it says | What it does NOT say / unknown |
|---|---|---|---|---|
| VRChat, OSC Overview | https://docs.vrchat.com/docs/osc-overview | 2026-11-05, full; updated 2025-11-13 | Enable via Action Menu, Osc, Enabled. VRChat receives on 9000 and sends on 9001. Default sender address 127.0.0.1; `--osc=in:IP:out` can point output at another device's IP. Warns that OSC programs are downloaded from the internet and to use only trustworthy ones. | No mention of UDP. No permission model, authentication or rate limit. Does not say how VRChat binds its listening socket (loopback only or all interfaces). No OSCQuery mention. |
| VRChat, OSC as Input Controller | https://docs.vrchat.com/docs/osc-as-input-controller | 2026-11-05, full; updated 2025-11-13 | `/chatbox/input s b n`: `b` true sends `s` immediately, skipping the keyboard; `b` false opens the keyboard pre-filled with `s`. `n` false suppresses the notification sound (default true). Text capped at 144 characters; at most 9 lines displayed, counting newlines and wrap. `/chatbox/typing b` toggles the typing indicator. | No rate limit. No wire encoding for the booleans (OSC 1.0 has no boolean tag in its standard set). Does not say whether 144 counts characters or bytes, or what happens when `s` is longer (truncate, drop, error). Does not say what happens if the keyboard is already open or the user dismisses it. Silent on character set. |
| VRChat, release notes 2022.2.2p3 | https://docs.vrchat.com/docs/vrchat-202222p3 | 2026-11-05, full; build 1229, dated 30 Aug 2022 | The original statement of the same endpoint, with the same `b` semantics. States that "right now" the OSC `input` endpoint supports only ASCII and that UTF-8 support will come later, while the chatbox display already supports UTF. | Historical. The current input page (above) does not repeat the ASCII limit, so whether non-ASCII input works today is **unknown** and unverified. |
| VRChat, OSC Avatar Parameters | https://docs.vrchat.com/docs/osc-avatar-parameters | 2026-11-05, full; updated 2025-11-13 | Values sent to `/avatar/parameters/<name>` set the matching avatar parameter (example: `VRCEmote`, Integer). `/avatar/change` announces the avatar ID. Config types are Int, Bool, Float. Per-avatar JSON configs are auto-generated under `AppData\LocalLow\VRChat\VRChat\OSC\{userId}\Avatars\`. With no config, one is generated that listens to and sends every message. States the config system is a stop-gap that "may be removed at some point". | Does not say whether a parameter is synced or non-synced, or whether non-synced ones can be written from outside. No full built-in parameter list. Does not say how custom parameters are handled. No permissions, range or rate limits. Unknown whether a wave gesture is reachable on an arbitrary avatar. |
| Open Sound Control 1.0 spec | https://opensoundcontrol.stanford.edu/spec-1_0.html | 2026-11-05, full | Transport-independent; a packet "can be naturally represented by a datagram" such as UDP. Ordering is specified only inside a bundle. | No delivery guarantee, acknowledgement or retransmission. No authentication, encryption or access control. Says nothing about VRChat's use. |
| W3C, WebXR Device API | https://www.w3.org/TR/webxr/ | 2026-11-05, **not read in full**: characters 0 to 400,000 of 411,340; the last ~11k were not seen | Candidate Recommendation Draft dated 29 October 2026. Section 10 defines input sources (target-ray modes including `gaze`, and `transient-pointer`, which hides sensitive input such as gaze behind OS intent). Section 13 covers consent, user activation, sensitive information and trusted-UI risks. `isSystemKeyboardSupported` exists on `XRSession`. | The text I read defines no speech recognition, voice, dictation or microphone API. It offers a system keyboard hook only. Eye-tracking data is treated as sensitive. The unread tail is mostly changelog and index, but I did not confirm that. |
| Khronos, OpenXR registry landing page | https://registry.khronos.org/OpenXR/ | 2026-11-05, landing page full; **spec itself not read** | OpenXR 1.1 is current. Specs offered as "all published extensions" and "ratified extensions". | No dates or extension names on this page. The 1.1 spec (xrspec.html) exceeded the fetch size limit, so the extension list was not read. I did not find a speech or voice extension, but that is a search result and not proof of absence. |
| Khronos, XR_EXT_eye_gaze_interaction | https://registry.khronos.org/OpenXR/specs/1.1/man/html/XR_EXT_eye_gaze_interaction.html | 2026-11-05, page full (it is a stub) | Instance extension, number 31, revision 2, ratified. | The page is a stub and states no privacy or permission rules. Whether runtimes require a user permission is unread. |

Secondary, not primary and not relied on: a web search showed that Microsoft's OpenXR plugin for Unreal carries a vendor speech extension (`XR_MSFT_HOLOGRAPHIC_REMOTING_SPEECH`) for keyword recognition. I did not read the Microsoft page, so treat this as a lead to check, not a finding.

## 2. Constraints these sources imply for any future adapter

These are design constraints derived from the documented behaviour above. They are proposals for XR-R03 and XR-R05 to ratify, not decisions.

1. **Hard-code `b = false`.** Only `b = false` leaves the final send with the user (the keyboard opens pre-filled). The adapter must not expose `b` as a setting or a command-line flag. Residual risk: the booleans' wire encoding is undocumented, so a sender could be misparsed as true. Only a real client can show that this never happens.
2. **144 characters: split with confirmation, or refuse. Never truncate silently.** Behaviour past the limit is undocumented. The adapter must check length itself (and the 9-line display limit) before sending anything. If the draft is longer, show the user the chunks and let them confirm each, or refuse and keep the draft local.
3. **Character set is an open question.** The 2022 notes say ASCII only. The current page is silent. Until a real client shows otherwise, non-ASCII text must be treated as possibly corrupted, and the user should see what was actually sent.
4. **Delivery cannot be verified.** OSC over UDP has no acknowledgement. VRChat's documented outputs (port 9001) are not documented to report chatbox receipt. "Sent" must never be displayed as "delivered"; the user's own view in the client is the only confirmation.
5. **Rate limits are undocumented.** Assume none exist and throttle on our side. Observed limits are an experiment output, not a documented fact.
6. **Avatar parameters are optional and allowlisted.** The docs do not guarantee that a parameter exists, is writable, or is stable (the config system may be removed). Absence of a parameter must mean no action.
7. **No ambient trust on the receiving port.** OSC has no authentication, so any local process can write to port 9000 as well. YazSes should only ever send, never listen on 9001, in a first experiment.
8. **WebXR and OpenXR offer no speech path in what I read.** Voice would come from YazSes (or a host app) outside those standards. WebXR's sensitive-input rules reinforce the design rule that gaze never commits an action alone.

## 3. Egress classification against ADR-019

Reading of [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md) and `tests/test_egress_inventory.py`. This is my interpretation, not an ADR decision.

| Question | Finding |
|---|---|
| Would an OSC sender be a new outbound path? | Yes. A UDP socket in a `src/yazses/` module is an outbound network primitive; the inventory test scans for `socket` and fails the build until the module is registered and classified. |
| Fetch or send? | It carries dictated text out of the process, so it is closest to Class B (send), like the loopback LLM-cleanup endpoint and the loopback side of `yazses remote`. The test currently asserts exactly two SEND paths, so a third needs an ADR-019 amendment and a deliberate test change. |
| Loopback only (127.0.0.1) | The documented default (sender 127.0.0.1, port 9000). The text stays on the machine but crosses to another process (VRChat, or any process bound to that port). Smallest exposure; still a registered SEND. |
| LAN | The OSC page shows `--osc=` can target another device. A standalone headset or a second PC would need a LAN route. That is a separate, stronger authenticated-transport design (see D7 in [DECISIONS.md](DECISIONS.md)), not an extension of loopback. I did not read VRChat's documentation for standalone-headset OSC, so I make no claim about it. |
| Never-escalate categories (ADR-019 section 3) | Other participants' voice in a world is third-party capture and may never leave. The adapter would carry only the user's own reviewed text. |

## 4. Gate status (copied from [ROADMAP.md](ROADMAP.md) entry gate)

| # | Gate before any implementation | State on 2026-11-05 |
|---|---|---|
| 1 | Substantive non-contributor demand, or a documented maintainer change to the evidence condition | **Not met.** Per the lead's brief an earlier XR implementation PR was closed unmerged on 2026-11-02 with "no XR implementation is planned"; I did not re-verify this on GitHub. No evidence log of demand exists (XR-R01 undone). |
| 2 | ADR-030 amendment that lifts or scopes the freeze for this experiment | **Not met.** The 2026-11-01 amendment names a single biosignal exception and says the freeze is not lifted. |
| 3 | Decision on transport, egress, consent and safety boundaries | **Not met.** DECISIONS.md D1 to D10 are open; section 3 above only frames D3, D5 and D7. |
| 4 | Bounded delivery milestone and issue set | **Not met.** Not applicable until gates 1 to 3 pass. |
| 5 | Baseline, realistic test environment; no unverified headset compatibility | **Not met.** No VRChat client or headset was available or used here. |

## 5. Experiment described, not implemented

Population and tooling come later. These hypotheses are written now so a failure would be unambiguous. Each would be run only after the gate passes, on a PC VRChat client the experimenter owns, with a throwaway avatar and no other participants present.

- **H1, no silent send.** With `b = false`, N predeclared trials (suggest at least 30 per condition) of a short phrase produce a pre-filled keyboard and **zero** messages in the world chat until the experimenter confirms. Falsified by one auto-send; the experiment then stops and the adapter is abandoned.
- **H2, text fidelity and limits.** Phrases of 1, 100, 144 and 145 characters (ASCII), plus a fixed set of accented, right-to-left and CJK samples and multi-line text, arrive in the keyboard intact. Record, per case: intact, altered, truncated, dropped. This resolves the ASCII question and the over-limit behaviour.
- **H3, avatar parameter reach.** On a test avatar the experimenter owns, writing an allowlisted parameter via `/avatar/parameters/<name>` produces the expected change when the parameter exists in the generated config, and has no effect and no error when it does not. Record which parameters are writable and whether the behaviour survives an avatar change.

Report simulated and real-client results in separate columns, with client build, OS and date, as [EVALUATION.md](EVALUATION.md) requires.

## 6. What was not done

- No VRChat client, headset, OpenXR runtime, browser WebXR session or Unity scene was run. All findings are documentation only and **hardware-unverified**.
- VRChat's Terms of Service and Community Guidelines were not read, so permissibility of external OSC tools is **not assessed** here.
- Sources were captured through a text-summarising fetch tool, not a raw download; wording above is paraphrase, and the quoted fragments should be re-checked against the live pages before they are cited elsewhere.
- The VRChat pages carry no version number, only the front-matter update date noted above, so a later reader must re-check them against the live site.
