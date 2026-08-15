# ADR-018 — Show the price before charging it; defer third-party plug-ins

**Status:** Accepted (2026-08-15)
**Supersedes:** the plugin-trust decision in [[adr-009]] (*Python Plugin SDK via Embedded
PyO3*), and with it the plugin-loading half of [[adr-001]]. See §3.
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-011]] (nothing leaves the machine), [[adr-016-dependency-budget]],
`design/research/2026-08-15-modular-distribution-survey.md`, issue
[#259](https://github.com/MSKazemi/yazses/issues/259) (the PySide6 move),
`docs/install-cost.md`

---

## Context

The brief: *a user who only wants voice dictation should install only what voice dictation
needs; anyone wanting more should fetch it separately, as a plug-in — so no machine carries
gigabytes it never uses.*

The survey that preceded this ADR measured the situation rather than assuming it, and the
measurement changed what the work is.

**The requested architecture already exists.** 21 optional extras, lazy imports at every
heavy call site, `yazses features enable <slug>` installing a feature's packages on demand
into the running interpreter (`system/deps.py`), models fetched on first use and never
shipped, and a published cost page. ADR-016 already forbids widening the base.

**And it is near its floor.** A clean base install on Linux x86_64 / CPython 3.12 is
**414 MB across 42 distributions**, of which **84% is four binary wheels that arrive with
the speech engine** — `ctranslate2` (135 MB), PyAV (103 MB), `numpy` (58 MB) and
`onnxruntime` (53 MB). YazSes' own code is **4 MB**. `onnxruntime` is `Required-by:
faster-whisper`, so it is not ours to remove.

So "make the dictation-only install smaller" has an honest answer: **it is already the
dictation-only install, and the floor belongs to faster-whisper's dependency tree.** The one
packaging lever with real leverage — Qt, 648 MB — was already pulled in #259.

That leaves two things genuinely missing, and one question that only looks like packaging.

## Decision

### 1. `yazses features` shows the **marginal** cost of enabling a feature. *(Do this.)*

Today the catalogue lists 144 capabilities with a description and an on/off state, and no
price. `features enable gaze` fetches mediapipe and OpenCV; `enable voiceprint` pulls
speechbrain and a torch stack. The user finds out by watching a progress bar. That is the
gap the brief actually describes, and it needs no new machinery.

**It must be the marginal cost, not the sum of the extra's contents.** The `tts`, `silero`
and `parakeet` extras each declare `onnxruntime`, which a base install already has via
faster-whisper — so a naive total would quote a user 53 MB they will not download. The
correct number is computable from what already exists: `_FEATURE_DEPS[slug]` gives
`(check_modules, pip_packages)`, and `deps.missing_modules(check_modules)` already reports
which are genuinely absent *on this machine*.

Sizes come from a small committed table with a generator, not a live PyPI query: the
catalogue must render offline, instantly, and identically for everyone. A stale figure is
acceptable and a hang is not.

### 2. A named `minimal` intent, and honest documentation of what each path installs. *(Do this.)*

Install paths currently ask for `desktop` or for nothing. `install.sh`, the `.deb` and the
Snap all pull `desktop`, correctly — so the 414 MB figure is **not** what most users get;
they get ~1.1 GB and should. But there is no way to say "this is a server, give me the
least" and be told what that means. Add the intent, and state per install path what it pulls.

### 3. Third-party plug-ins: **designed, deliberately not shipped.** *(Decide, do not build.)*

This is the part of the brief that reads as packaging and is not. **It also reverses an
accepted decision, so that is dealt with first.**

#### What ADR-009 decided, and why it no longer holds

ADR-009 (Accepted, 2026-05-18) specifies a plugin SDK: `yazses plugin install <name>`,
plugins in `~/.local/share/yazses/plugins/`, a `yazses_plugin.json` manifest scanned at
start-up, and — explicitly — *"Plugins run in the daemon process and are trusted (no
sandboxing in v1.0; v2 will add restricted sub-interpreters)."*

That decision was sound **for the system it was written about, which does not exist.**
ADR-009 and ADR-001 describe a **Rust core** with Python plugins behind a `python-plugins`
**cargo feature** — a build-time gate. In that design, "trusted, unsandboxed" is defensible
because plugin support is a compile-time choice a distributor makes, and a build without the
feature cannot load a plugin at all. Users who want the minimal, plugin-free daemon get one
that is *structurally incapable* of loading foreign code.

YazSes never migrated to Rust. It is a Python daemon, and there is no build-time gate
available: any plugin mechanism added to the shipped daemon is present and live for **every
install**, including the users who chose this tool specifically because of what ADR-011
promises. The safety property ADR-009 relied on is not merely unimplemented — it is
unavailable in the architecture that actually shipped.

Two further things changed after May: ADR-011's offline guarantee became the project's
principal, publicly advertised value proposition rather than one property among eleven, and
the project acquired its first real user. "Trusted, no sandboxing" is a different proposition
when the trust is being extended on someone else's behalf.

#### The decision

A YazSes plug-in would sit on the dictation hot path — with the microphone, the raw audio,
the transcript, and the injection backend. That is **every word the user speaks, and the
ability to type anything into any focused window.** ADR-011's promise is that nothing leaves
the machine. A third-party plug-in mechanism is the most direct way that promise gets broken,
and it would be broken by someone else's code wearing this project's name, on a user who
believed the promise because we made it.

The survey shows nobody has solved this cheaply. VS Code isolates extensions in a separate
host process, which is a substantial engineering commitment. Blender does not isolate at all
and accepts the consequence. Neovim has no trust model whatsoever. For a tool whose entire
value proposition is *your voice never leaves this machine*, the Blender/Neovim answer is not
available to us.

**Therefore: no third-party plug-in loading.** Not "not yet designed" — decided, with the
reason on record, so it is not reopened as an oversight.

What this costs is real and worth naming: a capability cannot exist without living in this
repository, and `test_feature_wiring_honesty.py` enforces that. The mitigation is that the
in-tree path is deliberately cheap — issue #164 exists precisely to make "add a capability"
a small pull request, and 65 designed capabilities are waiting for exactly that.

**What would change this decision:** an isolation boundary that survives a hostile plug-in —
a separate process with no network namespace and no injector handle, communicating over the
existing IPC. That is a real design, not a small one, and it is what ADR-009 deferred to "v2
restricted sub-interpreters" without costing. If it is ever built, this ADR is superseded
rather than amended.

**Note for anyone reading ADR-001/009 later:** they remain the record of a Rust-core design
that was not built. This ADR reverses only their plugin-trust position. Whether the Rust
migration itself is still intended is a separate question that neither this ADR nor the
current codebase answers — worth its own ADR rather than an assumption in either direction.

### 4. Do not design against PEP 771.

PEP 771 (*Default Extras*) is exactly the mechanism wanted for §2 — `pip install yazses`
meaning "minimal plus recommended", with `pip install yazses[]` as the opt-out. It is a
**Draft with no implementation in pip or uv**; reference implementations exist only in
unmerged branches. Revisit if it lands; build §2 without it.

## Consequences

**Good.** The user can see a price before paying it, which is the thing actually asked for.
The privacy promise stays enforceable, because there is no third-party code on the hot path
to enforce it against. No new dependency, no new trust surface, no new failure mode.

**Accepted cost.** The size table needs regenerating when dependencies change; a guard test
should fail when a feature gains a dependency the table does not know about, so it goes stale
loudly rather than silently. Sizes are download sizes and will not match a user's `du` — say
so where they are shown rather than pretending to a precision we do not have.

**Rejected, with reasons.**
- *A plug-in marketplace.* Requires a trust model, a review process and a distribution
  channel — for a project whose contributor funnel is the constraint, this creates work it
  cannot service.
- *Vendoring a smaller inference stack to cut the 414 MB.* The floor is faster-whisper's, and
  the `parakeet` engine seam already exists for engine substitution; that is an engine
  decision, not a packaging one.
- *Splitting YazSes into multiple PyPI distributions.* Moves the size problem into a
  resolution problem, and every extra already does this without a second package to publish.
