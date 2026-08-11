# ADR-v2-047 — Field-Aware Dictation

**Status:** Accepted (2026-07-02) · Wave G
**Context links:** [[adr-v2-007-atspi-pilot]] (navigates vs reads-one-attr), [[adr-v2-039-acoustic-profiles]] (env vs widget), [[adr-v2-036-smart-paste]] (app vs field), [[adr-011]]

## Context

Wave G research (#2) — read the OS accessibility **role** of the currently-focused widget and
auto-select a formatting profile: a number field gets digits (`42`, not "forty-two."), a search
box gets no trailing period, a password field is **refused** (never inject a spoken password).
Anchors: AT-SPI2 focused-object role/state, Windows UI Automation `ControlType`/`IsPassword`,
WCAG 1.3.5 "Identify Input Purpose". Same accessibility plumbing YazSes already uses for the
AT-SPI Voice Pilot.

Distinct from AT-SPI Voice Pilot (which *navigates/actuates* the tree) — this *reads one
attribute of the already-focused field to reshape output*. Distinct from Smart-Paste (adapts to
the *app*) and Acoustic Profiles (adapts to *room noise*).

## Decision

Add an opt-in **Field-Aware Dictation**: `[fieldaware] enabled=false`. Two pure cores:
`profile_for_role(role, states)` maps an accessibility role/state to a `FormatProfile`
(`capitalize`, `trailing_punct`, `digits_only`, `refuse`), and `apply_profile(text, profile)`
applies it — returning `None` for a `refuse` (password) field so the caller suppresses
injection. The role read comes from the existing platform accessibility layer (deferred wiring).
OFF by default.

## Consequences

- First feature that reshapes output by the *target field*; composes with Smart-Paste (app) and
  Redaction Ink (secrets).
- Pure role→profile map + apply → fully testable with no accessibility runtime.
- Safety: password-role refusal is a hard guard, aligning with the prohibited-credential rule.
- Privacy (ADR-011): reads only the local role string; no content leaves the machine.
- Caveat: poor accessibility trees give unknown roles → conservative default (normal prose);
  off by default.
