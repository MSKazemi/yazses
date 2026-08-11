# ADR-v2-106 — Checksum-Validated Data Entry

**Status:** Accepted (2026-07-02) · Wave M
**Context links:** itn, temporal, [[adr-v2-091-spoken-table-csv]], slotfill, [[adr-011]]

## Context

Wave M research (#2) — in a reference-number field, dictating "credit card / IBAN / ISBN / …" runs
the spoken digits through the field's **check-digit algorithm** and refuses/flags a value that fails,
catching a Whisper digit slip before it lands. Entity ITN, Temporal Normalizer, Spoken Table, and
Slot-Filling *format* numbers; none *verifies* them. STT's single most damaging silent error is a
wrong digit in an account/ID number, and a checksum is the only way to catch it without a human
re-read — no dictation product does this. Anchor: check-digit systems are *designed* to catch
transcription errors — Luhn (ISO/IEC 7812) catches ~98% of single-digit + adjacent-transposition
errors; IBAN MOD-97 (ISO 13616) >99%; ISBN-10/13, Verhoeff, ISO 7064.

## Decision

Add an opt-in **Checksum-Validated Data Entry**: `[checkdigit] enabled=false`. Pure cores in
`checkdigit/validate.py`: `validate(digits, scheme)` → `(ok, normalized)` for `luhn` | `isbn10` |
`isbn13` | `verhoeff` (unknown scheme → `ValueError`), and `suggest_fix(digits, scheme)` →
single-digit-edit candidates that pass. Pure integer arithmetic; no dependency. OFF by default.

## Consequences

- Catches the most costly silent STT error (a wrong ID digit) before injection, and proposes fixes.
- Pure arithmetic → fully testable against known-good/known-bad numbers.
- Distinct from ITN/formatting (verify vs format).
- Privacy (ADR-011): local arithmetic; the number never leaves the machine (note: sensitive numbers
  are validated, never logged — honours redaction).
- Caveat: covers the common schemes (extensible); off by default.
