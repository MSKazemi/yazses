# ADR-v2-093 — Local Voice Timer & Break Reminder

**Status:** Accepted (2026-07-02) · Wave K
**Context links:** [[adr-v2-092-word-count-goal-tracker]] (session utilities), [[project_readback_loop]] (spoken alert), [[adr-011]]

## Context

Wave K research (#10) — set a timer or break reminder by voice ("set a timer for 25 minutes",
"remind me in an hour") entirely on-device, announced by read-back — no phone, no cloud assistant,
no context switch away from the keyboard. A Pomodoro/RSI-break accessibility aid for long dictation
sessions. Every commercial voice timer (Alexa/Siri/Google) is cloud-tied; a fully-offline one that
lives in your dictation daemon is genuinely unavailable elsewhere. Anchor: on-device assistant /
eyes-free reminders line of research; ties to the ergonomic-break literature.

## Decision

Add an opt-in **Local Voice Timer**: `[voicetimer] enabled=false`. Pure cores: `parse_duration(text)`
→ seconds (supports "25 minutes", "2 hours 30 minutes", "an hour", "half an hour"),
`format_duration(seconds)` → a spoken-ready string, and `parse_timer_command(text)` →
`("set", seconds)` / `("cancel", None)`. Dependency-free parsing; the daemon schedules the alert on
a background timer and the spoken alert reuses the existing TTS. OFF by default.

## Consequences

- Fully-offline voice timers/break reminders inside the dictation daemon.
- Pure duration parsing → fully testable; scheduling + TTS reuse existing infra.
- Privacy (ADR-011): local timer only; nothing scheduled in any cloud.
- Caveat: fires only while the daemon runs (session-scoped, not a persistent alarm); off by default.
