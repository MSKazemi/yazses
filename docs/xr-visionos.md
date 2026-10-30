---
title: XR on Apple visionOS (library, not yet connected)
description: What a visionOS companion app can and cannot give the YazSes XR adapter. Apple does not expose continuous eye gaze to third-party apps, so pointing degrades to a pinch-time ray, a head ray and hand joints. A tested library fed synthetic data only.
---

# XR on Apple visionOS

> **Status: a library, not a feature you can turn on.** `yazses.xr.visionos` is a pure,
> tested model of what a visionOS companion app can provide. Its tests use **synthetic**
> data only (invented matrices, joints and events). It is **not yet connected** to
> `XrSession`, the daemon or any transport, there is no config key and no command, and no
> Vision Pro app ships. Nothing here has been measured on a device. For the general adapter
> see [XR voice input](xr-voice-input.md).

## The limit you must plan around: no continuous eye gaze

**visionOS does not expose the user's eye gaze to third-party apps.** This is a deliberate
privacy decision by the platform, not a gap in the adapter, and nothing in YazSes can work
around it.

What Apple has said publicly:

- "To protect people's privacy, the system applies hover effects outside your app's
  process, so your app doesn't know where people are looking." (WWDC25, *Design hover
  interactions for visionOS*: <https://developer.apple.com/videos/play/wwdc2025/303/>)
- An Apple Vision Pro engineer on the developer forums: "For privacy reasons there is no
  way to read the location of a user's gaze." (<https://developer.apple.com/forums/thread/757357>)

The forum reply is a statement by an Apple engineer, not an API reference page. No page
that lists every gaze channel was found, and whether an enterprise-entitlement API offers
anything more was **not checked**. This library assumes there is no gaze channel and never
fabricates one.

Consequence for the device profile: `vision-pro` in `yazses.xr.devices` lists eye tracking
as unknown, which is safe. Read that field as 'a gaze ray the app can receive', not 'the
headset has eye cameras'. The headset does track eyes; the platform keeps the result.

## What a companion can provide

`yazses.xr.visionos.CAPABILITIES` is the machine-readable form of this table.

| Channel | Availability | Conditions | Evidence |
|---|---|---|---|
| Continuous eye gaze ray | **Not provided** | none | WWDC25 303; forum thread above |
| Hover state (what the user is looking at) | **Not provided** | system draws it, app is not told | WWDC25 303 |
| Selection ray (`SpatialEventCollection.Event.selectionRay`) | **Only at a pinch** | an input event must occur | [Event page](https://developer.apple.com/documentation/swiftui/spatialeventcollection/event) |
| Contact point (`location3D`), direct pinch or touch | Only at the event | the event kind is `directPinch` or `touch` | [Kind page](https://developer.apple.com/documentation/swiftui/spatialeventcollection/event/kind-swift.enum) |
| Hand skeleton (27 joints, `simd_float4x4`) | Continuous | **Full Space only**, user permission | WWDC24 10094, WWDC23 10082, [JointName](https://developer.apple.com/documentation/arkit/handskeleton/jointname) |
| Device (head) pose, `WorldTrackingProvider` | Continuous | the query is described as relatively expensive | WWDC23 10082 |

The shared-space restriction matters: Apple says that in the Shared Space, alongside other
apps, ARKit and hand tracking are not available. A companion that needs hands must run in a
Full Space.

### Joint count: 27, not 28

`HandSkeleton.JointName` lists **27** cases (`forearmArm`, `forearmWrist`, `wrist`, four
thumb joints and five joints for each of the four fingers). A figure of 28 is sometimes
quoted; the Apple page lists 27 and `HandJointName` carries those 27, spelled as Apple
spells them.

## Matrices, axes and units

Apple's transforms are `simd_float4x4`, which is **column-major**: elements 0 to 3 are the
x axis, 4 to 7 the y axis, 8 to 11 the z axis and 12 to 15 the translation. A joint in app
space is `originFromAnchorTransform * anchorFromJointTransform`
(WWDC24 10094 sample code; `HandAnchor.originFromAnchorTransform` is the wrist).

`rigid_from_column_major(values)` turns 16 numbers into a `RigidTransform` and refuses,
with `TransformError` and a reason, anything that is not a rigid motion: NaN or infinity,
a projective bottom row, **non-unit scale**, shear, a mirror image (negative determinant)
and absurd translations. Float32 noise inside 1e-4 is accepted and cleaned up. A RealityKit
entity transform can carry scale; strip it before it reaches this seam.

Axes: RealityKit is described as +X right, +Y up, -Z forward, in metres (WWDC24 10186,
WWDC23 10080; read through summaries of those transcripts, so second-hand). That ARKit's
origin frame and the device anchor follow the same axes is **unverified**: no Apple page
found says so. `Convention.VISIONOS` therefore stays an assumption. **Check the forward
axis on a device before trusting any direction**: hold the headset, face a known wall and
confirm `forward_ray` points at it.

## How pointing degrades

The adapter's binder resolves 'here' and 'this' from the pointing history around the word's
onset. It needs at least 3 usable samples in a window of 0.4 s before and 0.2 s after.

- On a gaze-capable headset that history is a stream of tens of samples per second.
- On visionOS the only gaze-derived sample is **one ray per pinch**. A window holds zero or
  one of them. The binder returns NONE ('insufficient evidence'), by design, rather than
  guess. `window_evidence` counts what a window holds and says whether the floor is met;
  the test suite runs the real binder on both cases.

So the adapter falls back, best first (`VisionOSPointer.choose`):

1. **Pinch ray** (`PINCH_RAY`): the system's look-and-pinch `selectionRay`, if it is at most
   `pinch_ttl_s` (default 1.0 s) old. It is reported with source `EYE` because the system
   derived it from gaze at that instant. It is a single moment, never a stream.
2. **Direct touch** (`DIRECT_TOUCH`): for a direct pinch or touch, a ray from the latest head
   position through the contact point, so the ordinary panel ray-cast lands on what was touched.
3. **Hand ray** (`HAND_RAY`): off by default (`use_hand_ray`). See the next section.
4. **Head ray** (`HEAD_RAY`): the device anchor's forward direction, continuous but **not
   gaze**. It is stamped with low confidence (0.4) and points where the head faces, which
   is not where the eyes rest.
5. **Nothing** (`NONE`), with the reason. It never invents a ray.

Rules that keep this honest:

- **No re-stamping.** The pinch ray keeps its real timestamp. A pinch from 0.8 s ago is not
  turned into a fresh-looking time series, which would fabricate gaze the platform withheld.
- **No history kept here.** `VisionOSPointer` holds the latest sample per channel. The
  rolling window, with its bound and its privacy rules, stays in `SampleRetention`.
- **Last pinch ray as a single shot.** `nearest_pinch_sample` finds the pinch closest in
  time to the spoken word (positive skew means the user pinched after the word). That is
  one observation, not a distribution: send any binding made from it through confirmation.

Expected user experience on visionOS: dictate by holding a pinch (the gesture pipeline
works as on any platform), and say 'put it here' while looking at the target and pinching.
Text goes to the panel the pinch ray hit when the pinch and the word are close in time.
Without a pinch near the word, the adapter has only the head ray and will ask, or refuse,
rather than pick a panel.

## Derived pinch rays (hand-anchored)

`derived_pinch_ray` builds a ray from an anchor through the pinch point (the midpoint of
`thumbTip` and `indexFingerTip`). It is **not gaze**.

| Anchor | Origin | Works when | Fails when |
|---|---|---|---|
| `FOREARM` | `forearmArm` joint (the `wrist` if that joint is untracked) | the user raises the hand and points | the hand rests low, as in an indirect pinch: the ray points at the lap |
| `HEAD` | device position | the pinch is held up in the line of sight | the hand is low; origin is off by the eye-to-device offset (a few cm, unmeasured) |

Apple's own description of indirect input is that the hand is 'held closer to your body'
(WWDC24 10094), which is exactly when a hand-anchored ray is least meaningful, so
`use_hand_ray` defaults to off.

**Error.** Joint-position noise alone tilts the ray by about `hypot(σ_origin, σ_target) /
baseline` (`pointing_error_rad`). With 1 cm of noise at each end, an 8 cm lever arm is off
by about 10 degrees and a 30 cm arm by about 3 degrees. A baseline under 8 cm is refused
(`None`) rather than amplified. This is only the measurement-noise term: whether the line
people intend to point along is the line assumed here is the larger, unmeasured error.

## Pinch detection

`PinchDetector` turns hand frames into `PINCH_START` / `PINCH_END` events from the
thumb-tip to index-tip distance, with hysteresis: start at or below `close_m` (0.02 m),
end at or above `open_m` (0.035 m), hold in between. A tracking dropout shorter than
`lost_grace_s` (0.15 s) keeps a held pinch; a longer one ends it with confidence 0.5
(inferred). Out-of-order frames are dropped and counted. These thresholds are guesses to
be measured; whether Apple's joint origins sit at the fingertip surface is not stated by
the pages read. It is a custom gesture for the Full Space; the system's own pinch arrives
as an input event instead.

## What is unverified

- Whether `selectionRay` refreshes during a held pinch (the model assumes one ray per pinch).
- The coordinate space of `selectionRay`: the companion must convert it to the canonical
  frame (the forum reply shows `convert(_, from: .local, to: .scene)`).
- That ARKit's origin frame and the device anchor use +Y up, -Z forward.
- Apple's `Phase` cases (the adapter keeps its own begin/end).
- Whether the device-pose query needs permission.
- Any enterprise-entitlement API that might expose more.
- Every number in `PinchConfig` and `PointerConfig`.

## Privacy by platform

Apple's choice and this adapter agree: the user's gaze history is the sensitive thing, and
on visionOS it never reaches the app, so it cannot reach YazSes either. What does arrive
(a pinch-time ray, a head pose, hand joints) is still treated as sensitive: it flows only
through `SampleRetention`, is never written to disk and is never sent anywhere. The module
imports nothing outside the standard library and the `yazses.xr` package, and a test scans
its source for network and disk-write primitives.

## For integrators

A Swift companion would: run `HandTrackingProvider` and `WorldTrackingProvider` in a Full
Space, flatten each `simd_float4x4` column by column into 16 numbers, convert
`selectionRay` / `location3D` to the canonical frame, and send plain numbers. This library
has no transport yet; see [what is not built yet](xr-voice-input.md#what-is-not-built-yet).
