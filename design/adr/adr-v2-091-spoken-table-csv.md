# ADR-v2-091 — Spoken Table → CSV / Field Data Entry

**Status:** Accepted (2026-07-02) · Wave K
**Context links:** [[adr-v2-059-spoken-spreadsheet]] (nav/formulas vs bulk entry), [[adr-v2-063-slot-filling-dictation]], [[adr-011]]

## Context

Wave K research (#7) — a row/column dictation mode: "row: Ada, 1815, London" injects tab/comma-
separated cells and advances; "next row" moves down. For spreadsheets and forms. Distinct from
Spoken Spreadsheet (cell *navigation/formulas*) — this is *bulk structured row/field data entry*
with a delimiter + Tab/Enter cadence, a data-entry accessibility workflow. Anchor: Vocal Forms
(IJSREM 2025), VaaniSevak offline Vosk census entry.

## Decision

Add an opt-in **Spoken Table→CSV**: `[tablecsv] enabled=false, delimiter=","`. Pure cores:
`parse_row(text)` strips a leading "row/entry/record" marker and splits into cells;
`rows_to_delimited(text, sep)` splits multiple "next row"-separated rows into delimited lines; and
`row_plan(cells, cell_key, row_end)` emits an injection plan (type cell → press Tab, … → press
Enter). Dependency-free. OFF by default.

## Consequences

- Bulk hands-free row/field entry for spreadsheets and forms; pure parse + cadence.
- Distinct from Spoken Spreadsheet (bulk entry vs navigation).
- Privacy (ADR-011): local text + keystrokes only.
- Caveat: cell splitting is on commas/"and" → free-form cell text with commas needs quoting (a
  later tier); off by default.
