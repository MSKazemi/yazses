# ADR-020 — Agent protocols: which one YazSes needs, and which it must not adopt

**Status:** Accepted (2026-08-15)
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-v2-006-spoken-mcp]] (YazSes as an MCP *client* — already decided),
[[adr-019-egress-inventory-and-escalation]] (the AF_UNIX boundary this leans on),
[[adr-011]], [[adr-018-feature-packs-and-the-plugin-question]], the problem space §B1–B2

---

## Context

The question was whether YazSes needs agent-to-agent communication, MCP, FastMCP, or
FastAPI — and in which scenario. Four different things are routinely conflated under
"agent protocol", and the answer is different for each:

| | What it actually is | Status here |
|---|---|---|
| **MCP client** | YazSes calls tools other people expose | **Decided** — ADR-v2-006, designed, unwired |
| **MCP server** | Other agents call YazSes | Undecided — this ADR |
| **A2A** | Autonomous peers negotiating tasks | Undecided — this ADR |
| **FastAPI / HTTP** | A transport, not a protocol | Undecided — this ADR |

Treating them as one question is how a project ends up adopting a protocol because it is
current rather than because something needed it.

## Decision

### 1. MCP **server**: yes, for exactly two tools, over stdio only

The genuinely novel thing YazSes could offer another agent is not transcription — it is
**a human**. An agent that has stalled on a decision only a person can make currently has
one way to ask: put text on a screen and wait for someone to notice, read and type. Voice
is the cheapest interrupt a working human can service, because it needs neither their eyes
nor their hands.

Two tools, and only two:

- **`transcribe(path)`** — an offline transcript of a file. Useful, unglamorous, and
  already the CLI; exposing it costs nothing new.
- **`ask_human(question, timeout)`** — speak a question, capture the spoken answer, return
  it as text. This is the one that does not exist anywhere else.

**Over stdio, never HTTP.** MCP's stdio transport keeps the server a child process of the
thing that spawned it — the same property that makes YazSes's own IPC safe. Which brings
us to the next decision, because it is the same decision.

### 2. FastAPI / any HTTP server: **no**, and the reason is structural

YazSes's IPC is JSON-RPC over an `AF_UNIX` socket. [ADR-019](adr-019-egress-inventory-and-escalation.md)
records why that matters and enforces it with a test: `AF_UNIX` is a filesystem object, not
an address, so the daemon is unreachable from another machine **by construction** rather
than by configuration. There is no port to leave open, no bind address to get wrong, no
firewall rule standing between a user's dictation and the network.

Adding FastAPI would replace that structural guarantee with a configuration one. The
daemon holds a live microphone and can type into any focused window; "we bound to
127.0.0.1" is a much weaker sentence than "there is no socket that could reach the
network." An HTTP surface is also precisely what an ADR-018-style plug-in would have been:
a general-purpose door onto the dictation hot path.

**If a genuine need for HTTP appears** — a browser client is the plausible one — it is a
new ADR that supersedes this, with an isolation story, not a dependency added to `pyproject.toml`.

*FastMCP is a library for building MCP servers, not a separate protocol; where it is
convenient for the stdio server above, it is an implementation detail governed by
[ADR-016](adr-016-dependency-budget.md) like any other dependency.*

### 3. Agent-to-agent (A2A): **no**, because YazSes is not an agent

A2A protocols assume autonomous peers that negotiate, delegate and pursue goals. YazSes
does not have goals. It is an **input device with a state machine** — it turns held keys
and speech into text and keystrokes, and every decision it makes is a classification, not
an intention.

Adopting A2A would mean inventing agency in order to have something to negotiate with. The
scenarios that sound like they need it — "the coding agent asks YazSes to dictate", "YazSes
delegates transcription to a bigger model" — are a tool call and a config option
respectively. **MCP already covers both directions of the only relationship that exists**:
YazSes calls tools (ADR-v2-006), tools call YazSes (§1).

### 4. The hard part is the interrupt budget, not the plumbing

`ask_human` is where the real design problem is, and it is not a protocol problem.

**An agent that can speak to you at will can interrupt you at will.** A voice interrupt is
cheap for the agent and expensive for the human, which is exactly the asymmetry that
produces notification fatigue — and this one arrives in the middle of the user's sentence,
on the same audio channel they are dictating into.

So `ask_human` ships with these, or does not ship:

- **Off by default**, like everything else.
- **A budget** — a configurable maximum number of interrupts per hour, and no way for a
  caller to exceed it by asking harder.
- **Never during a hold.** The user is speaking; the daemon knows it; the question waits.
- **The caller is named** in the spoken question, so "who is asking" is never ambiguous.
- **The answer goes back to the caller, not into the focused window.** A dictation burst
  answering an agent must not also type into whatever the user had open — the no-text-target
  guard's failure mode in reverse.

### 5. Nothing here is scheduled

This ADR decides *what would be acceptable*, not what happens next. The MCP client from
ADR-v2-006 is itself still unwired, and wiring a server before the client is finished would
add surface to something incomplete. The `agent` slug stays in `_UNWIRED` until someone
takes it.

## Consequences

**Good.** The question "should we add FastAPI?" now has a written answer with a reason
stronger than taste. The one genuinely novel capability — an agent asking a human a
question out loud — is described precisely enough that someone could build it, including
the part that makes it survivable.

**Accepted cost.** Choosing stdio over HTTP means YazSes cannot be called by something on
another machine. That is the intended property, not a limitation to work around later.

**What would reverse this.** For §2: a real user need for a browser client, plus an
isolation design. For §3: YazSes acquiring goals of its own, which would be a different
product. For §1: nothing — it is already the narrow version.
