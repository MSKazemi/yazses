# ADR-MOB-004 — Activation on mobile: hold-the-mic-key, with a hold/toggle accessibility switch

**Status:** Accepted (2026-08-07) · design only, no code yet
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-mob-003]] (IME), [[adr-011]] (no ambient capture),
[[adr-v2-129]] (activation-source seam on desktop),
desktop analogue: `src/yazses/hotkeys/hold_detector.py`

---

## Context

The desktop's defining interaction is **hold-to-talk**: press and hold a key, speak,
release, the words appear. It is not an arbitrary choice — it is what makes "no ambient
capture" ([[adr-011]] §9) true by construction: the microphone is open exactly while a
human is physically holding something down.

A phone has no keyboard to hold, so the interaction must be re-derived rather than copied,
and the derivation has to survive three constraints the desktop does not have:

1. **`RECORD_AUDIO` is while-in-use.** An app can capture only while it is foreground, or
   from a `microphone`-typed foreground service — and Android 14+ blocks *starting* such a
   service from the background. Any activation gesture that fires while YazSes is not on
   screen therefore cannot simply open the mic. (Meeting Mode's FGS is [[adr-mob-007]].)
2. **A held finger occupies the screen.** Holding the mic key is natural, but it conflicts
   with users who cannot sustain a press — the accessibility constituency that YazSes
   explicitly serves (`adr-v2-012`, `adr-v2-021`).
3. **Always-listening is disqualified by [[adr-011]]**, which forbids ambient capture
   outright. A wake word is not a small feature on mobile; it is the abandonment of the
   product's central privacy claim, and on battery it is expensive besides.

## Decision

1. **Primary: press-and-hold the mic key on the YazSes keyboard.** Down → start capture
   (with the same pre-speech ring-buffer padding the desktop uses, so the first word is not
   clipped); up → stop, decode, deliver. The desktop's hold-debounce semantics
   (`hold_detector.py`: a key must be held ≥ N ms before a burst starts, so a stray tap is
   not a burst) port directly and are covered by contract vectors ([[adr-mob-008]]).
2. **A user-selectable hold/toggle switch, defaulting to hold.** In toggle mode a tap
   starts and a second tap stops, with a hard safety cap (`max_burst_seconds`, default
   120 s) and a persistent, unmissable recording indicator. This is an accessibility
   requirement, not a convenience: it must be present in M1, not deferred.
3. **Secondary, M2: the headset button.** A wired or Bluetooth headset's
   `KEYCODE_HEADSETHOOK` / media-button press maps to start/stop *while the YazSes keyboard
   is the active input method*. This gives a genuinely hands-free path within the
   permission model, with no always-on mic.
4. **Tertiary, M3, opt-in: the floating bubble** ([[adr-mob-003]] §5) — a draggable mic
   button over other apps, for users who want to keep their own keyboard. Requires the
   overlay grant; off by default.
5. **A Quick Settings tile and a launcher shortcut start Meeting Mode**, which is a
   deliberate, visible, user-initiated foreground action — the only capture path that
   outlives the on-screen UI, and it shows a permanent notification for its whole life
   ([[adr-mob-007]]).
6. **No wake word, no ambient capture, no "raise to speak", in any milestone**, unless a
   future ADR supersedes [[adr-011]] — which is not anticipated.
7. **The activation source is an interface, not a hard-wired listener**, mirroring the
   desktop's activation-source seam from [[adr-v2-129]]: `:core:session` exposes
   `ActivationSource` with `onHoldStart`/`onHoldEnd`, and the IME key, the media button, the
   bubble and (later) a watch or a hardware switch are all just implementations. This is
   what makes external-switch accessibility hardware a contributor-sized addition rather
   than a refactor.

## Consequences

- The mic is open only while a finger is down, a toggle session is explicitly running, or
  Meeting Mode is explicitly running — so [[adr-011]]'s no-ambient-capture claim holds on
  Android with the same strength as on desktop, and the app can say so without hedging.
- Hold-to-talk on a touchscreen has a failure mode the desktop lacks: the finger slides off
  the key. The key must keep the burst alive while the pointer is anywhere in the keyboard
  view and end it on `ACTION_UP`/`ACTION_CANCEL`, and the visual state must make an ended
  burst obvious. This is a named acceptance test, not a detail.
- Toggle mode reintroduces the risk the hold model eliminates (a session left running).
  Mitigated by the hard cap, the ongoing indicator, and auto-stop on prolonged silence
  (the desktop's semantic-autostop idea, `adr-v2-029`, is the natural M3 upgrade).
- The headset-button path only works while YazSes is the active IME, which will surprise
  someone; the setting's description must say it.

## Rejected

- **Wake word / always-listening** — contradicts [[adr-011]] §9, drains battery, and would
  make the app's central claim false. The desktop's own wake-word ADR (`adr-v2-033`) is
  likewise unshipped for the same reason.
- **Volume-key or power-key hold as a global hotkey.** Requires an `AccessibilityService`
  to intercept keys globally ([[adr-mob-003]] rejects that grant), hijacks a control users
  need for media and for the camera, and is fragile across OEM skins.
- **Shake-to-dictate / proximity-sensor gestures.** High false-positive rate; opening a
  microphone on an accidental gesture is exactly the failure this project must never have.
- **A persistent notification with a mic action as the primary path.** Android's
  notification-action latency and the extra tap make it worse than the keyboard key for the
  common case; it survives as part of Meeting Mode only.
