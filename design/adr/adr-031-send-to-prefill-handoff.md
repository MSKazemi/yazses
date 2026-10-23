# ADR-031 — "Send to": hand dictated text to a desktop AI client, pre-filled and never sent

**Status:** Accepted (2026-10-23)
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-030-agent-era-direction]] (Pillar 2, bridge 1),
[[adr-019-egress-inventory-and-escalation]] (*Reached by handing a URL to another program*),
[[adr-v2-132-assisted-bug-reporting]] (option (b): prepare, never send — the precedent),
[[adr-021-invest-in-error-cost]], [[adr-011]].

Evidence labels: **[M]** measured in this repository · **[F]** a primary source says so
(accessed 2026-10-22) · **[O]** engineering judgement · **[U]** not verified.

---

## Context

A user who dictates a prompt for a desktop AI client can already do it: focus the client's
input box, hold the hotkey, speak. YazSes types into it like any other window [M]. Two
things make that worse than it needs to be:

- the dictation has to start with the client focused and the caret in its input box, so a
  thought spoken while reading a document or a terminal has to be re-spoken or copied;
- a long prompt dictated into a chat box that sends on Enter is one mis-recognised
  "new line" away from being sent half-finished.

Both desktop clients that the agent-era user runs most publish a URL scheme that opens a
new conversation with the prompt **pre-filled for review**:

| Client | URL | Behaviour (as documented) |
|---|---|---|
| Claude desktop (macOS, Windows, Linux) | `claude://claude.ai/new?q=<text>` | new chat, prompt box pre-filled, user reviews and sends; values URL-encoded; text cut at about 14,000 characters [F] ([Open Claude Desktop with a link](https://support.claude.com/en/articles/14729294-open-claude-desktop-with-a-link)) |
| Claude Code, in Claude desktop | `claude://code/new?q=<text>` | same, for a Claude Code session [F] (same page) |
| Codex app | `codex://new?prompt=<text>` | new local thread with the prompt; does nothing without a `prompt`, `path` or `originUrl` parameter [F] ([Codex app commands](https://developers.openai.com/codex/app/commands)) |

A third-party security report claims that a crafted `claude://` link could submit a prompt
without a send action [U]. It contradicts the vendor's documentation; it is the reason this
ADR treats "never sent" as something verified per client and per release, not assumed.

There is no equivalent for Gemini, and no mail client is in scope (ADR-030 §4).

## Decision

### 1. A hand-off verb, off by default

A new opt-in capability, `sendto` (`[sendto] enabled = false`), adds one action:
**hand the current text to a named client, pre-filled**. The text is, in order of
preference:

1. the staged-dictation buffer, when staged mode is on — "send to Claude" becomes a commit
   target beside typing it, so a long prompt is reviewed in YazSes's buffer first;
2. otherwise the last dictation burst, *instead of* typing it.

It is reachable as a spoken command (the exact phrases are the decider's, below), from the
CLI as `yazses send-to <client> [TEXT]` for scripts and keybindings, and it never types into
the focused window.

### 2. A closed list of targets, custom schemes only

Targets are a fixed table in a pure module (`sendto/targets.py`): `claude`, `claude-code`,
`codex`, each with its scheme, path and parameter name. **The user cannot configure a
URL.** A configurable template is a configurable exfiltration endpoint.

**No `https://` fallback, ever.** `https://claude.ai/new?q=` opened in a browser sends the
text to a server in the page request, *before* the user reviews anything [O]. That would
be an egress path that carries dictated text, which ADR-019 permits only through its
escalation rules. A custom scheme is resolved by the operating system to a locally
installed program; when the client is not installed, the hand-off fails and says so.

### 3. Why this adds no egress path

YazSes already places dictated text into these clients — by typing it. The hand-off moves
the same text into the same program by a different local mechanism; the client transmits
it only when the user sends it, exactly as with typed text. ADR-019 gets one row in
*Reached by handing a URL to another program*, classified like ADR-v2-132's pre-filled
issue: *dictated text → a local program; nothing is transmitted by YazSes*.

Two local exposures are new and are handled, not waved away:

- **The URL is visible locally while it is being opened.** An opener that spawns
  `xdg-open <url>` puts the text in a process argument list that other local users can
  read. The opener sits behind a new platform seam (`platform/base.py`, implemented per
  OS) that passes the URL by the platform's in-process API where one exists (macOS
  `NSWorkspace`, Windows `ShellExecuteW`) and documents the argv exposure where it does
  not.
- **Logs.** `system/browser.py::open_url` logs the URL on failure. The hand-off does not
  reuse it as-is: it logs the target and the text *length*, never the text.

### 4. Limits are refusals, not truncation

Text longer than the target's documented limit (Claude: about 14,000 characters) is
refused with the length and the limit, and stays in the staged buffer. A truncated prompt
sent to an agent is a different prompt.

### 5. "Never sent" is tested against the client, not the documentation

A validation row per client and OS records that the hand-off pre-fills and does not
submit, on the client version tested. The capability's `features info` names the client
versions it was verified on. If a client is ever observed to submit on open, its target is
removed in the next release and the release notes say why.

## Consequences

- One pure module (targets, encoding, limits), one platform seam, one spoken command, one
  CLI command, one config section, one ADR-019 row. No dependency.
- Linux is the first platform (ADR-030). macOS and Windows openers ship with it but stay
  *preview* until a validation row exists.
- The agent-era docs page can show "dictate, review, send to Claude" as one flow.

## Decisions (2026-10-23)

The decider answered the three questions this record left open when it was proposed.

1. **Spoken phrases: one fixed phrase per target** — *"send to Claude"*, *"send to Claude
   Code"*, *"send to Codex"*. Each is a whole utterance, anchored at both ends like staged
   mode's commit grammar; there is no *"send that to <name>"* pattern with a slot.
2. **`claude-code` is a separate target**, reached by *"send to Claude Code"* and opening
   `claude://code/new?q=`, not a sub-mode of `claude`.
3. **The CLI form `yazses send-to <client> [TEXT]` ships in the first release**, beside the
   spoken one.

## Implementation notes (2026-10-23)

Where the build differs from §1–§5, or chose something the record left open:

- **The opener seam (§3) now exists (second build, 2026-10-23).** The first build had
  none — its default opener was `system/browser.py::open_url(url, log_url=False)`, so
  Linux used `webbrowser`'s `xdg-open` and macOS and Windows whatever `webbrowser` does
  there — because another branch was editing `platform/base.py`. That branch (#649, the
  `FileOpener` seam) has landed, and `platform/base.py` now has a `UrlOpener` Protocol
  beside it: `open_url(url)`, one backend per OS family in `platform/<os>/fileopen.py`,
  chosen by `platform.get_url_opener()` without building a `Platform`. The default opener
  in `sendto/handoff.py` calls it only for a scheme in the closed target table (an
  allow-list), and every backend first refuses a web, file or script scheme, a URL
  without a scheme, and whitespace or control characters
  (`platform/base.py::require_local_scheme`, a deny-list behind the allow-list), before
  it starts anything. No backend logs the URL, sends the child's output anywhere but
  `/dev/null`, or raises an exception whose message quotes it.
  - **Linux and the BSDs:** `xdg-open <url>`, the URL one argv element, no shell. Waits
    up to 5 s for its status: non-zero (4 = no program for the scheme) is a failed
    hand-off; still running is a hand-off, left alone and reaped in the background.
  - **macOS:** `NSWorkspace.sharedWorkspace().openURL_` in-process, as §3 asks; if
    PyObjC cannot be imported, `open <url>`. **Unverified:** no Mac, and whether
    `openURL_` may be called off the main thread, as the daemon does, is not established.
  - **Windows:** `os.startfile`, i.e. `ShellExecuteW` in-process. Unverified on Windows.
- **The local exposure that remains, stated (§3).** On **Linux**, `xdg-open` takes the URL
  as a command-line argument, so while it runs the text is in `/proc/<pid>/cmdline`:
  readable by every process of the same user and, unless `/proc` is mounted with
  `hidepid=`, by every other local user. The client the desktop starts receives the URL
  as an argument too (the `%u` of its `.desktop` entry), so if the hand-off *starts* the
  client, the text stays in that process's argument list for as long as it runs. A
  D-Bus hand-off through the desktop portal's `OpenURI` would remove the first half and
  is not built; the second half belongs to the client. On **Windows** YazSes starts no
  child, but the shell starts the client with the URL as its `%1` argument — the same
  second half. On **macOS** through `NSWorkspace` the URL travels as an Apple Event and
  no argument list holds it, except on the `open` fallback, briefly.
- **Limits (§4).** Claude and Claude Code refuse over 14,000 characters. Codex documents
  no limit, so it gets the same 14,000 (the narrowest choice). Every target also refuses
  an encoded URL over 32,000 characters, which keeps the URL inside Windows' command-line
  ceiling and Linux's per-argument one; text in non-Latin scripts reaches it sooner.
  Text with control characters other than tab, newline and carriage return, or that is
  not valid Unicode,
  is refused rather than altered.
- **Which text (§1).** With staged mode on, the buffer only: an empty buffer is refused,
  not replaced by an older burst. With staged mode off, the last burst the daemon typed,
  kept in memory only while `[sendto] enabled` is on. It has already been typed by then:
  a whole-utterance phrase cannot come before the words it sends.
- **The CLI with TEXT** hands off in the CLI's own process; the IPC method `send_to` takes
  a target name only, so no local caller can make the daemon open a URL with text of its
  choosing.
- **No `features` registry entry yet (§5).** The switch is `[sendto] enabled` in
  `config.toml`; a registry slug (and the per-client verified-version line in
  `features info`) waits for the validation rows.
- **Unverified:** no hand-off has yet been tried against a real Claude or Codex install on
  any platform.

## Alternatives considered

- **Type into the client (today).** Kept — it remains the default and works everywhere.
  This ADR adds a path for the two cases in §Context.
- **A configurable URL template.** Rejected (§2): it turns a convenience into an arbitrary
  outbound channel.
- **An `https://` web fallback.** Rejected (§2): it transmits before review.
- **Driving the client's own API or a browser automation.** Rejected: it sends on the
  user's behalf, which ADR-030 §4 rules out.
