# ADR-036 — Speech profiles and a hardware suggestion

**Status:** Accepted (2026-11-28; proposed 2026-11-27) · the pure module and a read-only `yazses model recommend` exist; no default, config key or download behaviour changes  
**Decision owner:** YazSes maintainer, who signed off on the three profiles on 2026-11-28, as [#930](https://github.com/MSKazemi/yazses/issues/930) requires for a new CLI command. The items under "Left open" are not part of that decision.  
**Tracking:** [#928](https://github.com/MSKazemi/yazses/issues/928) (epic), [#930](https://github.com/MSKazemi/yazses/issues/930) (workstream 2)  
**Context:** [ADR-030](adr-030-agent-era-direction.md) §3 (breadth freeze), [ADR-033](adr-033-reproducible-asr-evaluation-gate.md), [ADR-034](adr-034-parakeet-recommendation.md), [ADR-035](adr-035-model-download-policy.md)

## Context

A user chooses a speech model by checkpoint name. Three English checkpoints have error-rate,
memory and size measurements in [`docs/benchmarks.md`](../../docs/benchmarks.md), and
[`docs/how-to/low-ram-models.md`](../../docs/how-to/low-ram-models.md) already says which to
use at which memory size. Nothing reads the machine and applies that advice.

## Decision

1. **Three profiles:** `fast` = `tiny.en`, `balanced` = `base.en` (the default), `accurate` =
   `small.en`; `tiny`, `base`, `small` for another language or auto-detect. Parakeet is not a
   profile before the ADR-033 gate passes ([#645](https://github.com/MSKazemi/yazses/issues/645)).
2. **Installed RAM decides.** Under 3 GB: `fast`. Otherwise, and when RAM cannot be read:
   `balanced`, or the model the language profile already names (`small` for Mandarin).
3. **The CPU count never decides.** No committed measurement compares the three models across
   core counts. A machine with fewer than four logical CPUs is told that no timing in the
   benchmarks covers it.
4. **`accurate` is never picked for English.** On the benchmark laptop `small.en` was the
   slowest of the three by a wide margin.
5. **Advice only.** `yazses model recommend` reads and prints. It writes no config and fetches
   nothing.
6. **No `yazses doctor` row.** A different suggestion is not a fault: `small.en` chosen on
   purpose would be flagged on every run
   ([ADR-021](adr-021-invest-in-error-cost.md)). Doctor keeps reporting whether the configured
   model is present.
7. **Figures are copies.** The module repeats the published numbers and a test fails when they
   differ from the benchmarks page. No decode time is repeated.

## Left open

- `yazses model use fast|balanced|accurate`, which would write `[stt] model`. It changes the
  config and may need a download, so it should follow ADR-035's decision.
- #930 asks for a table derived from `scripts/bench-decode-latency.py`. The committed results
  of that script cover `base.en` on one two-core laptop only, so they cannot rank profiles or
  support a rule on CPU count. Running it for all three checkpoints on several machines is the
  evidence that rule would need.
- The 3 GB line has not been tried on small hardware, and the multilingual checkpoints have no
  row in the profile table.

## Alternatives considered

- **Pick by CPU count.** Rejected: unmeasured.
- **Pick `accurate` on a large machine.** Rejected: more memory does not shorten the wait, and
  nothing committed says which machine makes `small.en` quick enough for dictation.
- **A `[stt] profile` key.** Rejected: a second name for `[stt] model` would need a precedence
  rule, and a profile whose meaning changed in a release would change a user's model silently.
