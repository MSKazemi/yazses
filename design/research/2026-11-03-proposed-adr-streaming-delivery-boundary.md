# Proposed ADR — Streaming output is provisional until a safe delivery boundary

**Status:** Proposed for maintainer decision (2026-11-03); **NOT accepted**  
**Issue:** [#796](https://github.com/MSKazemi/yazses/issues/796) · Parent [#787](https://github.com/MSKazemi/yazses/issues/787)  
**Research:** [Streaming endpointing and commit safety](2026-11-03-streaming-endpointing-and-commit-safety.md)  
**Spec:** [Streaming commit replay protocol](../specs/streaming-commit-replay-protocol.md)  
**Scope:** design only during the [ADR-030 breadth freeze](../adr/adr-030-agent-era-direction.md)

This is an **ADR candidate in the research directory**, deliberately **not a numbered accepted ADR** and not an edit of generated ADR indexes. It becomes a numbered ADR only if a maintainer chooses to adopt it in a separate reviewed change.

## Context

YazSes' existing StreamingEngine emits LocalAgreement-2 stable prefix deltas from re-decoded accumulated audio. The live StreamingInjector immediately types these deltas into the active application and later selects and replaces them with the authoritative final transcript. A lock and seal fix historical partial-vs-final races, but cannot make focus, caret, Unicode selection, target acceptance or a partially completed OS injection atomic.

The specific audited code-path risk is that `[streaming]` starts live partial injection even when `[staged]` is enabled, while the ordinary stage-only return from `_on_hold_end` does not cancel those partials. A deliberate review buffer must not already have typed unreviewed speech into a shell, editor or agent prompt.

For long agent prompts a speaker may think silently for many seconds. A physical hold means **continue listening regardless of silence**. Separately opted-in hands-free auto-stop has different semantics; combining them would silently change the intent boundary.

## Proposed decision (conditional, **not yet binding**)

1. **Authority:** only an actual physical hold release (or the separately chosen hands-free control's accepted stop signal) authorizes finalization; silence, stable prefix, pre-warm and speculative decode are never themselves permission to finalize.
2. **Delivery:** all partial hypotheses and revisions are provisional. When staged mode is enabled, no provisional hypothesis may leave the daemon as keystrokes/clipboard, even on model or target errors; a private preview may display it without commit. This should be **safety-fixed first in a separately approved code PR**.
3. **Exactly one final decision:** classification, filtering, safety/target guards and staged policy must resolve before any final external delivery. A successful staged append must only touch the in-memory buffer. The user initiates a separate staged commit. Outside staged mode, final delivery happens once after release when allowed.
4. **Owner safety:** an injected-character count is an account of an attempted action, not proof that text remains at the same caret. If the target, focus, selection, user edits or completion status cannot be verified, the pipeline must **not perform blind cleanup**. Fail visibly, retain recoverable local text and request an explicit user action in any future approved design.
5. **Replay before deployment:** define a pure deterministic event/transition oracle, then audit the existing streaming engine/injectors/daemon path using synthetic traces. Gate any future user-visible change on both invariant tests and named hardware/application verification.
6. **No additions by implication:** current batch default, `[streaming] enabled=false`, physical hold semantics, API/config compatibility, offline requirement and zero-new-egress position stay unchanged. This proposal authorizes **no new model, dependency, UI feature, default or release**.

## Alternatives

| Alternative | Decision at proposal stage | Consequence |
|---|---|---|
| Keep existing live partial overwrites without replay gates | Reject | Leaves staged-path conflict and app-dependent cursor deletion unproved |
| Always send all partials to the staged buffer | Reject | Partial revisions can poison reviewed chunks; only the **final** text should be stageable |
| Disallow `[streaming]+[staged]` as an immediate narrowly scoped safety fix | Prefer as an interim implementation option **only if owner approves** | Simpler than adding private preview; existing streaming decode may be skipped without breaking final staged output |
| Add private local partial preview, never external partial typing | Defer implementation pending evidence | May preserve feedback without risking target edits, but must protect transcript privacy |
| Silence-based hard finalization of a physical held-key prompt | Reject | Wrong model of a thinking pause; keep separate hands-free semantics |
| New SimulStreaming/AlignAtt backend | Defer | More compute, model, model-license and packaging validation; does not solve external-target transaction semantics |

## Invariants for approval

- **I1**: zero external keystrokes and clipboard writes between physical hold start and approved final delivery while staged mode is on.
- **I2**: never finalize a physical hold before its release; no silence event can cause the release.
- **I3**: final external text is delivered at most once per burst; a failure cannot silently retry after partial side effects.
- **I4**: no late poll/decoder event writes after the burst is sealed.
- **I5**: no unproved deletion of pre-existing application content, including after a target focus/caret change.
- **I6**: reviewed, staged text remains recoverable if the external commit fails.
- **I7**: defaults and disabled-path behavior match the current product, no new egress/telemetry.

The companion [replay specification](../specs/streaming-commit-replay-protocol.md) supplies fixture structure and negative cases. Simulated passing tests **do not** constitute Linux/Wayland/macOS/Windows editor validation.

## Consequences, risks and unknowns

**Benefits:** a defensible trust boundary and reproducible failure taxonomy without expanding the product. Allows evidence-based comparison of batch, provisional preview and live injection. **Costs:** a conservative default offers less real-time text feedback; future per-app validation and recovery UX may be substantial. **Unknowns:** true desktop failure frequency; target API capabilities on each OS; latency/energy benefit of preview; model behavior during long-pause prompts.

## Review / acceptance gate

Requires a maintainer's explicit decision, evidence from a synthetic daemon-level staged+streaming reproducer and review of the existing injection/target assumptions. If accepted, allocate a real ADR identifier, update the generated index using its generator, and separately authorize a scoped delivery issue. **Until then, this is a proposed research document, not a statement that runtime behavior changed.**
