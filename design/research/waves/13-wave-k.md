# Wave K — SoA research, 10 net-new features

**Date:** 2026 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** fed [adr-v2-085](../../adr/adr-v2-085-chorded-shortcut-synthesis.md) through
[adr-v2-094](../../adr/adr-v2-094-focus-class-auto-profile.md). See the [waves index](README.md).

> A snapshot of the field, kept as the research record behind the ADRs it fed. Feature status
> should be checked against `yazses features` and the linked ADRs, not this note.

All on-device, off by default, distinct from the 82 features existing before this wave (v2 +
Waves D-J). Ranked strongest-first; anchors web-verified at the time (2025-2026). Prioritized
for accessibility and "needs local keyboard/window/selection/clipboard state" — the class of
feature a cloud tool can't reach.

1. **Chorded Shortcut Synthesis** — parse an arbitrary spoken modifier+key chord on the fly
   ("press control shift P", "escape twice", "hit F5") and inject it — not a pre-registered
   macro. Anchor: Apple Vocal Shortcuts (iOS 18, on-device), Talon chords, Apple Voice Control.
   Pure: `parse_chord(text)` → KeyChords, reuses the existing key-sequence injector. The biggest
   motor win in the set. → [adr-v2-085](../../adr/adr-v2-085-chorded-shortcut-synthesis.md).
2. **Focus-Class Auto-Profile Switching** — the daemon watches the focused window's app class and
   auto-activates the matching profile (grammar/vocab/cleanup/verbatim/injector). Anchor: Talon
   app-context, wlrctl/GNOME Window Calls/KWin/AT-SPI. Pure: `resolve_profile(window_class, map)`;
   focus-poller deferred to the platform layer. Distinct from manual per-app modes (automatic).
   → [adr-v2-094](../../adr/adr-v2-094-focus-class-auto-profile.md).
3. **Voice Undo/Redo Timeline** — a ring of the daemon's own injection events so you can undo/redo
   its output across bursts by voice ("undo the last sentence", "go back before I said X"), even
   where Ctrl+Z is unreliable. Anchor: VoiceRev / Commanding-and-Re-Dictation TOCHI. Pure:
   `InjectionTimeline` (append + undo(scope)/redo → backspace/retype deltas). The
   highest-leverage core in the set (also unlocks #8). → [adr-v2-089](../../adr/adr-v2-089-voice-undo-redo-timeline.md).
4. **Voice Case & Identifier Transform on Selection** — "make this snake_case / Title Case /
   camelCase" over the clipboard selection. Anchor: Cursorless format actions, Serenade. Pure:
   `transform_case(text, style)`; uses the existing clipboard. Distinct from Spoken Code Mode
   (dictates new vs transforms existing). → [adr-v2-087](../../adr/adr-v2-087-voice-case-transform.md).
5. **Auto-Pairing & Wrap-Selection for Code** — balance `() [] {} "" '' ``, "wrap this in parens".
   Anchor: Serenade enclosure handling, Cursorless wrap. Pure: `balance_delimiters` + `wrap`.
   Balancing/wrapping semantics literal dictation lacks. → [adr-v2-088](../../adr/adr-v2-088-auto-pairing-wrap.md).
6. **Inline Compute** — "what's 15% of 240" → types 36; date math. Anchor: Apple Math Notes (iOS
   18). Pure: `evaluate(expr)` safe arithmetic/percent grammar (`ast`); sympy/date-math deferred.
   Distinct from unit conversion/LaTeX/temporal (evaluates vs converts/formats).
   → [adr-v2-086](../../adr/adr-v2-086-inline-compute.md).
7. **Spoken Table → CSV / Field Data Entry** — "row: Ada, 1815, London" → tab/comma cells + cadence
   (cell→Tab, row→Enter). Anchor: Vocal Forms (IJSREM 2025), VaaniSevak offline. Pure:
   `rows_to_delimited` + cadence machine. Distinct from Spreadsheet (nav vs bulk entry).
   → [adr-v2-091](../../adr/adr-v2-091-spoken-table-csv.md).
8. **Session Bookmarks & Resume** — "bookmark here", "jump to my last bookmark"; anchors map to
   timeline positions (builds on #3). Anchor: VoiceRev / Just-Speak-It UIST. Pure: `BookmarkStore`.
   Distinct from Spoken Recall (positions vs content). → [adr-v2-090](../../adr/adr-v2-090-session-bookmarks.md).
9. **Word-Count & Writing-Goal Tracker** — "how many words so far?", spoken goal progress via
   read-back. Anchor: eyes-free editing (UIST). Pure: `WordGoalTracker`. Eyes-free utility.
   → [adr-v2-092](../../adr/adr-v2-092-word-count-goal-tracker.md).
10. **Local Voice Timer / Break Reminder** — "remind me in 20 minutes to stretch", pomodoro; local
    notification. Anchor: Stretchly microbreaks, MTD/RSI vocal-rest literature. Pure:
    `parse_duration(text)` + `TimerScheduler`; notification backend deferred. Distinct from
    Vocal-Strain Guard (user-set timer vs strain signal). → [adr-v2-093](../../adr/adr-v2-093-local-voice-timer.md).

## Ship-now pure (do first)
#1 `parse_chord`, #6 `evaluate`, #4 `transform_case`, #5 `balance_delimiters`/`wrap` — cleanest
dependency-free cores; #3 `InjectionTimeline` is the highest-leverage slightly-larger core
(unlocks #8). Caveats from the original sweep: #2's auto-switch is anchored to Talon
app-context (an ongoing product, not one paper); #8/#9 lean on established eyes-free-editing
literature rather than a single result.

Citations here have not been re-verified against [`research/verify_refs.py`](../verify_refs.py).
