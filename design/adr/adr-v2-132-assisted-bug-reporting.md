# ADR-v2-132 — Assisted bug reporting: what a "send this as an issue" button may do

**Status:** Proposed (2026-08-17) — **drafted in response to an inbox request; no code
written, nothing decided.** Requested as: *"improve the error detection of yazses and
create notification for error it detects for the user and say what user should do, also
capabilities of the automatic error report — can you do it with github issues, user just
accepts and allows and it automatically sends error as bug"*
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-011]] (zero telemetry — the promise this must not break),
[[adr-019]] (the egress inventory and the rule for adding an eighth), [[adr-012]]
(the learning corpus is machine-bound and encrypted)

---

## Context

Two of the three things asked for already exist, and it is worth being precise about
which, because it changes the size of the decision.

**Error detection exists.** The daemon already classifies every burst's outcome, and as
of this cycle summarises it (`typed: 6 of 14 recent bursts`). `doctor` runs eleven
checks, `verify` walks the real chain and names the first broken link, `report` builds a
redacted local bundle.

**Telling the user what to do exists.** `system/notify.py` sends actionable desktop
toasts with buttons, and the mic guard uses them. Every diagnostic message added this
cycle names a command to run.

**Filing the issue does not exist, and it is the only part that is a decision rather
than work.** Everything above is local. Filing crosses the machine boundary.

### Why this cannot be a small feature

ADR-011 promises nothing leaves the machine. ADR-019 makes that checkable: **seven**
outbound paths are enumerated, `tests/test_egress_inventory.py` fails the build when an
eighth appears unregistered, and of the seven exactly **two** can carry what the user
said — `llm_cleanup` (confined to loopback) and `remote/local_proxy` (the host named on
the command line).

An issue filer would be the **eighth**, and unlike the model-weight fetchers it uploads
*content from this machine to a third party*. It is the first path whose payload is
assembled from the user's own logs and configuration rather than being a request for a
public artifact.

That is not a reason to refuse it. It is a reason for it to be designed rather than
added.

## Decision

**Not yet taken.** Three options, with what each costs.

### (a) Do nothing beyond today

`yazses report` already writes a redacted bundle and prints the issue URL. The user
attaches it themselves.

*For:* zero new egress, zero new failure modes, and the user sees exactly what is sent
because they send it.
*Against:* it is the step where most people stop. A bug that is easy to hit and tedious
to report is a bug that gets hit repeatedly and reported once.

### (b) Prepare, never send — **recommended**

A notification offers **"Prepare a bug report"**. YazSes builds the bundle, opens the
browser at GitHub's issue form with the title and body **pre-filled**, and attaches
nothing automatically. The user reads the filled form and presses submit — in GitHub's
UI, with their own account, having seen every word.

*For:* removes the tedium, not the consent. **Adds no egress path at all** — the browser
makes the request, not YazSes, so ADR-019's inventory is unchanged and the eighth entry
is never created. Works with no token, no account setup, and no new dependency.
*Against:* the body must fit in a URL (~8 kB practical limit), so the bundle is
summarised rather than complete; large logs still need a manual attachment.

### (c) File directly via the GitHub API

YazSes holds a token and POSTs the issue.

*For:* one click, complete payload.
*Against:* the eighth egress path, and the worst-shaped one — it needs a credential, it
can file **without the user seeing the final text**, a bug in redaction becomes a public
disclosure with no human in the loop, and "user just accepts" is consent to a category
rather than to a specific payload. It also invites the failure mode where a crash loop
files a hundred issues, which is precisely the shape of the `#309` flood in the tracker
today.

## Consequences if (b) is chosen

- `report.py` gains a `summarise_for_issue()` — pure, size-bounded, reusing the existing
  redaction rather than a second one. Redaction must be **one** implementation or the
  two will drift, which is this repo's most frequent defect.
- The toast gains one button. `notify.py` already supports actions and already degrades
  to a plain toast, then to log-only, and never raises.
- Reuses `system/browser.py::open_url`, the single URL opener, which returns a bool and
  never raises.
- **ADR-019's inventory does not change**, and its test should keep passing untouched.
  If implementing this requires editing that test, the implementation has gone wrong.
- Needs a guard that the prepared body contains no `[REDACTED]`-eligible pattern —
  the existing `redact_text` tests extended to the issue body, not duplicated.

## Open questions for the decider

1. Is **(b)** enough, or is the one-click of (c) the point of the request?
2. If (c) is ever wanted, it needs its own ADR: token storage, rate limiting, and an
   explicit answer to "what stops a crash loop filing a hundred issues".
3. Should the offer appear only on a *repeated* fault, the way the mic guard waits for a
   streak? A prompt on every transient error is a prompt people learn to dismiss.
