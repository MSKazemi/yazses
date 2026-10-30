---
title: XR voice input from a web page (WebXR, library only)
description: How a web page on a headset browser can feed the YazSes XR adapter through the WebXR Device API, what each input mode can and cannot provide, the permission and privacy notes, and a JavaScript illustration that this package does not run. Library only, nothing is connected.
---

# XR voice input from a web page (WebXR)

> **Status: a mapping library and a design, not a feature you can turn on.** The
> `yazses.xr.webxr` module converts WebXR values (plain numbers and strings) into the
> XR adapter's types and wire frames. It is tested with **synthetic** data only: invented
> poses and invented timestamps, no headset, no real gaze, no audio. It opens no
> connection and runs no JavaScript. There is no `[xr]` config section, no command, and no
> transport that carries a page's frames to YazSes, so nothing here runs in an installed
> YazSes. No accuracy or latency has been measured on any browser or headset, and none
> is claimed. This page is for a person writing the companion page. For the rest of the XR
> adapter see [XR voice input](xr-voice-input.md).

## Why a web page

A browser is the lowest-friction way to put a companion on a headset: no native app, no
store review, one page for Meta Quest Browser, Safari on visionOS and Chrome on Android XR
or on a desktop with a headset. The page reads the user's pointing ray and select
events through the **WebXR Device API** and hands plain numbers to the adapter. The
trade-off is that the browser decides what a page may see, and on some headsets it
deliberately hides the most useful thing (the gaze).

This package covers the numbers. It does **not** cover how the page is served, how its
frames reach the desktop, or how audio gets there. Any server that hosts the page or
receives its frames is a new network path and needs an escalation under ADR-019 before it
exists; nothing in `yazses.xr` does either.

## The four input modes

A WebXR `XRInputSource` reports `targetRayMode`, one of four strings. The module accepts
exactly these and refuses anything else (a browser that adds a mode tomorrow is
reviewed before its rays count as pointing).

| `targetRayMode` | What it is | Recorded as | Ray available | What the deixis binder gets |
|---|---|---|---|---|
| `gaze` | A ray from the viewer along the direction it faces | `head` | While the source exists | A **head** ray history. It is never recorded as `eye`: the W3C text says the ray follows the direction the viewer is *facing*, and a W3C TAG review asked whether "gaze" there means eyes or head, so it is not treated as eye tracking |
| `tracked-pointer` | A handheld controller or a tracked hand | `controller`, or `hand` if the page saw `inputSource.hand` | Every frame while tracked | A rolling history: the best case for "type here". The pose can be unavailable while tracking is lost (unverified) |
| `screen` | A touch, mouse or stylus action | `controller` (no `screen` source exists; adding one is a reviewed `types.py` change) | Only for the action: a *transient* input source | Rays only while touching |
| `transient-pointer` | An operating-system interaction intent; used by Safari on visionOS for gaze plus pinch | `hand` | Only from pinch to release | **No history before the pinch** (see below) |

`handedness` is `none`, `left` or `right`; gaze, screen and transient-pointer sources
are expected to report `none` (unverified). The module keeps handedness and the source's
`profiles` strings as metadata only; nothing depends on them.

The ray itself is the source's `targetRaySpace` pose. The specification defines the ray as
running along that space's **-Z axis**, so the direction is the transformed (0, 0, -1)
and the origin is the pose's `position` in metres. WebXR's axes are right-handed, +Y up,
-Z forward, which is the package convention, so no conversion happens. The quaternion
order is WebXR's `x, y, z, w` (w last). For `[x, y, z, w]` the direction is
`(-2(xz + wy), 2(wx - yz), 2(x^2 + y^2) - 1)`; an identity orientation looks along
(0, 0, -1), and a +90 degree pitch about +X looks straight up. A quaternion within 1e-3
of unit length is renormalised, anything else is refused.

One consequence for integrators: the page must report rays **and panels in the same
reference space** (`local` is enough; it is always granted in an immersive session). A
reference-space reset moves the origin; send panels again afterwards.

## What `transient-pointer` loses, plainly

On Safari for visionOS the input list is empty until the user pinches. A
`transient-pointer` source then appears, its ray starts at the gaze, and from then on it
**follows the hand, not the eyes**. After `select` and `selectend` the source is removed
(Apple's WebKit post, linked below). The browser gives a page no continuous eye data, on
purpose, and the page cannot work around that.

The deixis binder (`bind_demonstrative`) wants rays from about 0.4 s before a word's onset
to 0.2 s after, and needs at least 3 usable samples covering at least 0.05 s. With
transient pointers:

- **Nothing before the pinch.** Rays exist only from `selectstart`. If the user says
  "type here" as they pinch, the lead window is empty and only the post-onset part can
  count. If they are *not* pinching (for instance a different trigger started the
  microphone), there are no rays and the binder returns *none*: the safe outcome, since it
  declines rather than guesses.
- **Not a gaze trace even while pinched.** The ray is steered by the hand. Saying "here"
  while the hand moves binds to where the hand points, which is a different question from
  where the eyes were.
- **A usable partial substitute: the head ray.** The viewer pose (`frame.getViewerPose`)
  is available every frame, so the page can also send it as a `head` sample
  (`WebXrFrameEncoder.viewer_frame`). That gives the binder a continuous history of where
  the head faced. Head direction is a coarse proxy for gaze, and it mixes into the
  same session as another source, so treat it as a fallback, not equivalence.
- **Hold-to-talk works.** `selectstart` to `selectend` spans the pinch, so the
  hold-to-talk path is unaffected; only the pointing history is thin.

## Events: `select` is not a hold

Hold-to-talk needs both edges. WebXR's primary action fires `selectstart` when it begins,
`select` when it **completes**, and `selectend` when it ends or the input source is
disconnected. The squeeze family is the same with `squeezestart`, `squeeze`,
`squeezeend`. `InputEventMapper` therefore maps:

| WebXR event | Gesture | Note |
|---|---|---|
| `selectstart` | `pinch_start` | the "pinch" name is the package's; the primary action may be a trigger, a pinch or a tap |
| `selectend` | `pinch_end` | passed on even with no start seen: the safe direction for a microphone |
| `select` while the action is held | nothing | its `selectend` carries the edge; reporting it would double-count |
| `select` shortly after `selectend` | nothing | a straggler must not become a tap, which in `toggle_tap` mode flips the microphone |
| `select` with no start or recent end | `tap` | a page or device that reports only `select` can toggle but **never hold** |
| `squeezestart` / `squeezeend` | `squeeze_start` / `squeeze_end` | |
| `squeeze` alone | nothing | there is no squeeze-tap gesture |

The W3C text fixes the order `select`, then `selectend` for a transient source's action;
for other sources the order is unverified, which is why the late-`select` guard exists.
When a source disappears (`inputsourceschange`) call `source_removed`, and when the session
ends call `end_session`: both emit the `*_end` gestures that close the microphone. A
session ending mid-action without a `selectend` is unverified, so do not rely on the
browser to say so.

## Timestamps: milliseconds, coarsened, jittered

`XRSession.requestAnimationFrame` passes `(time, frame)` where `time` is a
`DOMHighResTimeStamp`. It is **milliseconds** from the page's time origin. The wire
format takes **seconds** (`device_time_s`), so divide by 1000. The module does this and
rejects: strings, booleans, NaN and infinity, negatives, and anything above 1e12 ms. That
last bound catches `Date.now()` (about 1.7e12). A *seconds* value passed as milliseconds
cannot be recognised by looking at one number; the downstream `ClockMap` refuses a
stream whose clock runs a thousand times slow.

Browsers deliberately **coarsen** these timestamps and may add **jitter** to defend against
timing attacks and fingerprinting. MDN gives the specified resolutions as 0.005 ms
(cross-origin isolated) and 0.1 ms otherwise "or a coarser implementation-defined
resolution", and says the figures are not accuracy guarantees. Treat that as a
documented precision limit, not an error:

- **Equal stamps pass through.** Several frames, or several input sources in one frame,
  can share a tick. The module does not spread them out; that would invent precision the
  browser withheld.
- **A small step back is clamped** to the previous stamp (default tolerance 1 ms) and
  counted in `FrameTimeline.clamped`; the output never decreases.
- **A big step back is refused** (clock restart, mixed streams) until `reset()`.
- **A forward jump of any size is accepted** (a hidden tab stops producing frames).
- **If a browser rounds much more coarsely** (believed to be true of some
  fingerprinting-resistance modes; unverified), `FrameTimeline.min_positive_step_ms`
  shows it. Samples then arrive in runs with equal stamps and the binder, which credits
  evidence by elapsed time, has little to work with; it declines rather than guess
  (a test pins that it never names a wrong panel on a stream rounded to 100 ms).

Poses and DOM events are stamped by different mechanisms and the event clock's origin is
unverified, so `WebXrFrameEncoder` keeps one timeline per stream. A page that wants one
clock should stamp events with `performance.now()` in the handler, as the illustration
does.

## Features and consent prompts

WebXR sessions are requested with `requiredFeatures` and `optionalFeatures` strings.
`session_init_features()` asks for the minimum: nothing required, nothing optional.

- `local` is always included in an immersive session. It is enough for rays and panels.
- `local-floor` always requires user consent in the W3C text. It is not needed.
- `hand-tracking` (W3C WebXR Hand Input) makes the user agent obtain **explicit consent at
  session creation**, because it returns new sensor data. It is **not needed** for
  `select`/`squeeze` or `targetRaySpace`, and YazSes never reads joints. Request it only if
  your own page uses it, as `optional`, and tolerate a refusal.
- `eye-tracking`: **no such feature descriptor was found** in the W3C WebXR specification or its
  Hand Input module (unverified; absence from the text read is not proof it exists
  anywhere). Safari on visionOS gives no continuous gaze by design. The module reports
  it as *unknown*, offers no switch for it, and a required feature the browser does not
  know may fail the whole session (unverified), so never list it as required.

A page is also normally served over HTTPS and starts a session from a user action
(unverified here; check the specification for your target browser).

## Privacy notes

- A ray reveals what the user looked at or pointed at. The adapter holds rays only in the
  bounded retention window described in [XR voice input](xr-voice-input.md) and never
  writes them anywhere; the page should send only what the adapter needs: the target ray
  pose per frame and the select/squeeze events, nothing else.
- Do not request joint data, do not send `profiles` or device identifiers to the desktop,
  and do not log frames. The wire layer's error messages can quote a short piece of a bad
  value; log counts, not frames.
- The browser's privacy limits are a feature: they exist so a page cannot get continuous
  eye data. This integration works within them and does not try to defeat them.
- Use **synthetic fixtures** for development. Do not upload a real person's gaze, audio or
  hand data to any tool or service while building against this.

## The serialisation, as tested Python

`WebXrFrameEncoder` is the specification of what the page sends, kept as tested code so the
axis, quaternion order, unit conversion and event semantics are pinned:

```python
from yazses.xr.webxr import WebXrFrameEncoder, describe_input_source

enc = WebXrFrameEncoder()
info = describe_input_source("tracked-pointer", "right")
enc.pose_frame(12500.0, info, [0.0, 1.6, 0.0], [0, 0, 0, 1], confidence=0.9)
# b'{"v":1,"t":"sample","device_time_s":12.5,"source":"controller", ...}'
enc.event_frame("selectstart", 12600.0, 0)   # gesture frame, pinch_start
enc.event_frame("select", 12900.0, 0)        # None: its selectend carries the edge
enc.event_frame("selectend", 12900.0, 0)     # gesture frame, pinch_end
```

Every frame it returns passes `decode_frame`, and every refusal is a `WebXrError` (a
`WireError`), so a host that already drops bad frames handles these the same way.
WebXR reports no tracker confidence; the default `1.0` means "the browser gave a pose",
not "the pose is accurate".

## JavaScript illustration (not run by this package)

> **This is an illustration only.** This package does not run it, ship it or test it as
> part of a feature; a test only checks that its pure functions compute the same numbers
> as the Python above. `sendToBridge` is a placeholder you provide: the transport (the
> paired bridge) is not built, and this page deliberately opens no connection.

```js
// Pure functions: no I/O. Mirrors yazses.xr.webxr (ray_from_pose, ms_to_seconds).
const MAX_MS = 1e12; // Date.now() (about 1.7e12) is the wrong clock and is refused

function rayFromTransform(transform) {
  // transform is an XRRigidTransform: position and orientation are DOMPointReadOnly.
  const p = transform.position;
  const o = transform.orientation;
  const n = Math.hypot(o.x, o.y, o.z, o.w);
  if (!(Math.abs(n - 1) <= 1e-3)) return null; // not a unit quaternion: send nothing
  const x = o.x / n, y = o.y / n, z = o.z / n, w = o.w / n;
  return {
    origin: [p.x, p.y, p.z],
    // the transformed -Z axis (the target ray runs along its space's -Z axis)
    direction: [
      -2 * (x * z + w * y) + 0,
      2 * (w * x - y * z) + 0,
      2 * (x * x + y * y) - 1,
    ],
  };
}

function sampleFrame(timeMs, source, transform, confidence = 1) {
  if (!Number.isFinite(timeMs) || timeMs < 0 || timeMs > MAX_MS) return null;
  const ray = rayFromTransform(transform);
  if (ray === null) return null;
  return JSON.stringify({
    v: 1, t: "sample",
    device_time_s: timeMs / 1000, // milliseconds in, seconds on the wire
    source, origin: ray.origin, direction: ray.direction, confidence,
  });
}

function sourceFor(inputSource) {
  switch (inputSource.targetRayMode) {
    case "gaze": return "head";
    case "transient-pointer": return "hand";
    case "tracked-pointer": return inputSource.hand ? "hand" : "controller";
    case "screen": return "controller";
    default: return null; // an unknown mode is not trusted as pointing
  }
}
```

```js
// Session wiring: browser APIs, still no transport of its own.
// sendToBridge(text) is yours to provide; this page does not define it.
async function start() {
  const session = await navigator.xr.requestSession("immersive-vr", {
    requiredFeatures: [], optionalFeatures: [], // the minimum; see "Features"
  });
  const space = await session.requestReferenceSpace("local");
  const held = new Set(); // sources with an open select/squeeze, to close on removal
  let sourceIds = new WeakMap(), next = 0;
  const id = (s) => { if (!sourceIds.has(s)) sourceIds.set(s, next++); return sourceIds.get(s); };

  const KIND = { selectstart: "pinch_start", selectend: "pinch_end",
                 squeezestart: "squeeze_start", squeezeend: "squeeze_end" };
  for (const name of Object.keys(KIND)) {
    session.addEventListener(name, (e) => {
      const key = id(e.inputSource) + ":" + name.replace(/(start|end)$/, "");
      if (name.endsWith("start")) held.add(key); else held.delete(key);
      sendToBridge(JSON.stringify({ v: 1, t: "gesture",
        device_time_s: performance.now() / 1000, kind: KIND[name], confidence: 1 }));
    });
  }
  // A bare "select" with no selectstart is a tap; with selectstart/selectend it is not.
  // The Python mapper shows the full rule; omitted here to keep the illustration short.

  session.addEventListener("end", () => { /* send a *_end for every key still in held */ });

  session.requestAnimationFrame(function onFrame(time, frame) {
    session.requestAnimationFrame(onFrame);
    for (const src of session.inputSources) {
      const src_name = sourceFor(src);
      const pose = frame.getPose(src.targetRaySpace, space); // may be null
      if (src_name && pose) {
        const text = sampleFrame(time, src_name, pose.transform);
        if (text) sendToBridge(text);
      }
    }
  });
}
```

## Sources

Fetched 2026-10-30 as plain public pages; their text was treated as data.

- W3C, [WebXR Device API](https://www.w3.org/TR/webxr/): target ray modes, `XRHandedness`,
  `targetRaySpace` and its -Z axis, `XRRigidTransform`, transient input sources, feature
  descriptors and consent.
- W3C, [WebXR Hand Input Module](https://www.w3.org/TR/webxr-hand-input-1/):
  `hand-tracking` and its explicit-consent requirement.
- MDN, [XRInputSource.targetRayMode](https://developer.mozilla.org/en-US/docs/Web/API/XRInputSource/targetRayMode),
  [XRInputSourceEvent](https://developer.mozilla.org/en-US/docs/Web/API/XRInputSourceEvent),
  [XRSession.requestAnimationFrame](https://developer.mozilla.org/en-US/docs/Web/API/XRSession/requestAnimationFrame),
  [DOMHighResTimeStamp](https://developer.mozilla.org/en-US/docs/Web/API/DOMHighResTimeStamp).
- WebKit, [Introducing Natural Input for WebXR in Apple Vision Pro](https://webkit.org/blog/15162/introducing-natural-input-for-webxr-in-apple-vision-pro/):
  the transient-pointer lifecycle on visionOS.

What was **not** verified: the select-before-selectend order for non-transient sources;
that an untracked input yields a null pose; the -Z orientation of the `viewer` space; the
time origin of `Event.timeStamp` versus the animation-frame time; per-browser timestamp
rounding; whether a session ending mid-action sends `selectend`; any `eye-tracking`
feature; HTTPS and user-activation requirements for a given browser.
