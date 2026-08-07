# ADR-MOB-003 — Text delivery: IME first, RecognitionService second, share/clipboard fallback

**Status:** Accepted (2026-08-07) · design only, no code yet
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-mob-001]], [[adr-mob-002]], [[adr-mob-004]] (activation),
[[adr-011]] (no ambient capture), desktop analogue: `src/yazses/inject/`

---

## Context

On the desktop, the hardest-won part of YazSes is *injection*: getting text into whatever
window has focus (`inject/auto.py`, xdotool/ydotool/wtype/clipboard, plus the "no text
target" guard in `inject/target.py`). Android has the same problem and a much better
answer, but the answer constrains the whole app.

The candidate surfaces, with what each actually buys:

| Surface | Reaches | Permission cost | Mic while active? |
|---|---|---|---|
| `InputMethodService` (a keyboard) | every text field in every app | user enables the keyboard in Settings; no runtime grant beyond `RECORD_AUDIO` | yes — the IME window is visible, so the app is foreground for the while-in-use rule |
| `RecognitionService` | apps that call `SpeechRecognizer`, incl. some launchers/keyboards | user sets the default recogniser (path varies by OEM/ROM) | yes, while the recognition session is active |
| Share sheet / `ACTION_PROCESS_TEXT` | anything that can share a file or select text | none | n/a (works on a file or a selection) |
| Clipboard | everywhere, but the user must paste | none (Android 10+ restricts *reading* the clipboard, not writing) | n/a |
| `AccessibilityService` | can set text in most fields, and read the screen | the scariest grant Android has; Play restricts it to apps whose core function needs it | yes |
| Overlay bubble (`SYSTEM_ALERT_WINDOW`) | a floating mic button over any app | "Display over other apps" grant | yes, while visible |

The precedent is informative: **Transcribro**, the closest FOSS neighbour (whisper.cpp +
Silero VAD on Android), ships exactly the IME + `RecognitionService` pair and nothing
riskier. That combination is the proven shape.

`AccessibilityService` deserves a hard look because it is the only surface that could
reproduce the desktop's "dictate into the focused field without changing the keyboard".
It is rejected below.

## Decision

1. **The IME is the primary and only *required* delivery surface.** `:feature:ime`
   implements `InputMethodService`; the YazSes keyboard is a compact bar — mic key, a
   status/level indicator, backspace, enter, an "undo last insert" key and a switch-keyboard
   key — not a full QWERTY. Text is delivered with `InputConnection.commitText()`.
2. **The IME does not implement typing.** Deliberate: it keeps the surface small, it keeps
   the app out of the "we can see everything you type" trust problem entirely, and it lets
   the user keep Gboard/HeliBoard/AnySoftKeyboard for actual typing. The mic key offers
   "switch back to previous keyboard" so a dictate→edit→dictate loop is two taps. If the
   community later wants a full keyboard, that is a separate ADR and a separate app module.
3. **`RecognitionService` is the secondary surface** (`:feature:recognition`), shipped in
   M2. It makes YazSes selectable as the device speech recogniser, so a *different*
   keyboard's mic button, or any app calling `SpeechRecognizer`, is served on-device by
   YazSes. It is best-effort by nature: whether and where a user can change the default
   recogniser varies by OEM and Android version, so the UI must state honestly when the
   setting is not reachable on this device rather than claiming success.
4. **Share/`PROCESS_TEXT` and clipboard are the fallbacks.** File-share → transcript is the
   M3 file-transcription entry point (desktop analogue: `yazses transcribe`). Clipboard is
   the guard path, mirroring the desktop's "no text target" behaviour: if `commitText`
   fails or there is no `InputConnection`, the transcript is **copied to the clipboard and
   the user is told** — never silently dropped.
5. **The overlay bubble is opt-in and off by default** (M3, `:feature:bubble`), for
   dictating into an app while keeping another keyboard active. Requires the overlay grant,
   and the app must work fully without it.
6. **No `AccessibilityService` in wave 1** — see Rejected. If it is ever added it will be
   a separate, clearly-labelled, off-by-default module with its own ADR, and it will
   *never* be a prerequisite for basic dictation.
7. **Delivery is behaviourally identical to the desktop where the contract says so:**
   continuation spacing between consecutive bursts, voice punctuation, disfluency
   filtering and command-vs-dictation classification all run in `:core:postprocess` /
   `:core:commands` before delivery, validated by the shared golden vectors
   ([[adr-mob-008]]).

## Consequences

- Enabling YazSes is a two-step onboarding (enable the keyboard in system Settings, then
  select it) that Android deliberately makes friction-ful, plus a scary-looking system
  warning about keyboards being able to collect what you type. The onboarding screen must
  address that warning head-on and truthfully: this keyboard has no typing surface, no
  network permission in the recognition path, and its source is public.
- Because the IME window is visible while recording, the app is "in use" for the
  while-in-use `RECORD_AUDIO` rule and needs no microphone foreground service for
  hold-to-talk. Meeting Mode does need one — see [[adr-mob-007]].
- Password fields (`InputType` variations with `TYPE_TEXT_VARIATION_PASSWORD`) must
  disable the mic entirely and say why. This is both a privacy duty and a
  no-surprises rule.
- The "no text target" concept carries over as "no `InputConnection`", giving the mobile
  app the same never-lose-your-words guarantee the desktop has.

## Rejected

- **`AccessibilityService` as the primary (or default) injector.** It grants the app the
  ability to read every screen and act on it — the single most-abused permission on
  Android, restricted by Play policy to apps whose core function requires it, and a
  permanent, prominent system warning for the user. YazSes' core function does *not*
  require it: the IME reaches every text field already. Taking that grant would trade the
  project's central promise (a tool you can trust with everything you say) for
  convenience. Non-negotiable for wave 1.
- **A full QWERTY keyboard in wave 1.** Enormous surface (layouts, locales, autocorrect,
  gesture typing, theming) with no relation to the product thesis, and it would put YazSes
  in possession of every keystroke. Rejected on both cost and principle.
- **Root / ADB-based `input text`.** Not shippable to normal users.
- **Replacing the system dictation with a hidden hook.** No supported API; would require
  a custom ROM.
