---
title: XR voice input, OpenXR companion guide (library, not yet connected)
description: What an OpenXR companion app (Monado, SteamVR, Quest, Android XR, Pico) must send to the YazSes XR adapter, how OpenXR poses, location flags, action states, hand joints and XrTime map onto the adapter's types, and which spec facts are verified or still unverified. A tested library fed synthetic data only; not connected to the daemon.
---

# XR voice input: the OpenXR mapping

> **Status: a library, not a feature you can turn on.** `yazses.xr.openxr` is a pure
> module with unit tests that use **synthetic** numbers only: invented poses, invented
> flag words, invented joint arrays. It is **not connected to the daemon**, there is no
> `[xr]` config section and no command, and **no OpenXR runtime or headset has ever been
> tested against it**. No accuracy figure exists and none is claimed. This page tells a
> companion-app author what the module expects. For the rest of the adapter see
> [XR voice input](xr-voice-input.md).

## What the module is, and is not

OpenXR is the Khronos standard that Monado (Linux), SteamVR, the Meta Quest runtime,
Android XR and Pico expose. A companion app on the headset calls the OpenXR API itself
(`xrLocateSpace`, `xrGetActionStateFloat`, `xrLocateHandJointsEXT`, ...). **YazSes never
calls OpenXR.** `yazses.xr.openxr` has no OpenXR, numpy or SDK import; it models the
*data* those calls return as plain Python numbers and tuples and maps it onto the
adapter's own types (`XrSample` for rays, `GestureEvent` for gestures). The companion
copies the numbers out and sends them (the wire format is in the
[main guide](xr-voice-input.md)); the module is the arithmetic on the desktop side.

Everything below is plain arithmetic: no clock, no global state, no network, no file
access. Bad input raises `OpenXrError` (a `ValueError`) and nothing else.

## Conventions

OpenXR and the adapter agree, so no axis conversion is needed: **right-handed, +X right,
+Y up, -Z forward, metres, seconds.** The OpenXR spec states this for the VIEW and LOCAL
reference spaces; STAGE is "+Y up" with X and Z aligned to the room rectangle.

A pointing ray is the pose's position (origin) plus the pose's **-Z axis** (direction).
For the eye-gaze pose the spec says the pose has "+Y up, +X to the right, and -Z
forward". For `aim` poses -Z is the universal convention, but this guide could not
confirm it as a sentence in the spec, so `aim_sample` takes a `forward=` argument
(default -Z) instead of hiding the assumption.

**Send rays in LOCAL or STAGE space, never VIEW.** A pose located in VIEW space moves
with the head, so a panel would seem to follow you around. The module refuses a ray
labelled `ReferenceSpace.VIEW`. It also cannot check that your rays and your panels were
located in the *same* space (it only sees the label), so that is your contract: choose
LOCAL or STAGE once and use it for both. Their origins differ.

## The mapping table

| OpenXR source | Where it comes from | Function | Adapter result |
|---|---|---|---|
| Eye gaze pose | `XR_EXT_eye_gaze_interaction`, profile `/interaction_profiles/ext/eye_gaze_interaction`, pose `/user/eyes_ext/input/gaze_ext/pose` | `gaze_sample` | `XrSample`, source `EYE` |
| Controller aim pose | `/interaction_profiles/khr/simple_controller`, `/user/hand/<hand>/input/aim/pose` | `aim_sample` | `XrSample`, source `CONTROLLER` |
| Hand aim pose | `/interaction_profiles/ext/hand_interaction_ext` (`XR_EXT_hand_interaction`), aim pose | `aim_sample(source=RaySource.HAND)` | `XrSample`, source `HAND` |
| 26 hand joints | `XR_EXT_hand_tracking`, `xrLocateHandJointsEXT` | `hand_joints_from_raw`, then `hand_pinch_sample` | `XrSample` (source `HAND`) plus a pinch strength |
| Pinch value (float) | `/user/hand/<hand>/input/pinch_ext/value`, or the derived `pinch_strength` | `HoldGesture(HoldKind.PINCH)` | `PINCH_START` / `PINCH_END` |
| Grasp or squeeze value (float) | `/user/hand/<hand>/input/grasp_ext/value`, or a controller squeeze value | `HoldGesture(HoldKind.SQUEEZE)` | `SQUEEZE_START` / `SQUEEZE_END` |
| Boolean click | `/user/hand/<hand>/input/select/click` (`khr/simple_controller`) | `ClickTap` | `TAP` on each press |
| `XrTime` (nanoseconds) | `predictedDisplayTime`, `XrActionState*::lastChangeTime`, `XrEyeGazeSampleTimeEXT::time` | `xr_time_to_seconds` or `XrTimeBase` | device-clock seconds for `wire.ClockMap` |

The **grip** pose is deliberately not mapped. Its job is to say how the hand holds an
object, not where it points; the spec calls the aim pose the one for "interacting with
objects out of arm's reach".

### Poses and the validity flags

An `XrPosef` is a position in metres and a unit quaternion `(x, y, z, w)`. You pass the
two as plain tuples plus the `XrSpaceLocationFlags` integer from the same
`XrSpaceLocation`:

```python
sample = gaze_sample(
    timestamp_s, location_flags,
    (px, py, pz), (qx, qy, qz, qw),
    ReferenceSpace.LOCAL,
)
```

The flags decide what happens, exactly as the spec says:

| Flags | Meaning (spec) | Result |
|---|---|---|
| position **and** orientation `VALID` | both fields may be read | a sample |
| either `VALID` bit clear | "must not read" that field | `None`, not an error (a blink or tracking loss is a normal frame) |
| `VALID` but not `TRACKED` | an inferred or last-known value | a sample with reduced confidence (default 0.4, a heuristic) |
| both `TRACKED` | actively tracked | confidence 1.0 |
| a `TRACKED` bit without its `VALID` bit | a runtime bug | `None` |

The sample's confidence is the weaker of its two components. Unknown flag bits are
ignored so a newer runtime does not break an older build. The numeric bit values
(`0x1`, `0x2`, `0x4`, `0x8`) are from the public header and are pinned by a test; the
spec pages consulted list the flag names only.

### Quaternions

The spec lets a runtime fail with `XR_ERROR_POSE_INVALID` when the orientation norm
deviates by more than 1 % from unit length, so the module accepts any quaternion within
1 % and **renormalises** it, and **rejects** anything further out, a zero quaternion, a
NaN or infinity, a `bool`, a string, or an integer too wide for a float. If your source
is known to send unnormalised quaternions, pass `tolerance=None` and the module normalises
explicitly (a zero quaternion is still refused: it has no orientation). Norms are computed
overflow-safely, so components near 1e308 or 5e-324 do not produce a false zero or infinity.
`q` and `-q` are the same rotation.

### Hand tracking and the pinch ray

`hand_joints_from_raw(space, joints)` takes the `XrHandJointLocationEXT` array as a list
of exactly 26 `(location_flags, (x, y, z), radius_m)` entries in `XrHandJointEXT` order
(PALM 0, WRIST 1, ..., THUMB_TIP 5, INDEX_TIP 10, ..., LITTLE_TIP 25). An entry whose
position is not valid becomes "unreadable" and its numbers are never parsed. A valid
position must come with a positive radius, as the spec requires of a runtime.

From the joints:

* `pinch_strength(hand)`: the distance between thumb-tip and index-tip centres, minus both
  joint radii (surfaces touch, centres do not), mapped linearly from "open" (default 6 cm
  gap, strength 0) to "closed" (default 0.5 cm, strength 1).
* `hand_pinch_sample(t, hand)`: a ray whose origin is the midpoint of the two tips and
  whose direction runs from the wrist through that point. If you can supply a shoulder or
  head position in the same space, pass `origin_hint=` and the ray runs from there through
  the pinch point instead; that is the steadier pointer. It returns `None` when a needed
  joint is unreadable or the direction is undefined.

These are **heuristics for synthetic data, not measurements**: the gap range, the ray
construction and the confidence rule are parameters, not facts about any device. The
module does not read the `pinch_ext/pose` input of `XR_EXT_hand_interaction`, because its
geometric definition could not be confirmed.

### Gestures from action states

`HoldGesture` turns a float action (0..1) into start/end events **with hysteresis**:
press at or above `press` (default 0.8), release at or below `release` (default 0.5), and
nothing in between, so a value hovering near one threshold cannot chatter. `update_bool`
feeds an `XrActionStateBoolean`. Rules worth knowing:

* `isActive == False` counts as released. A hold must never stay stuck on because the
  input source vanished.
* A NaN, an infinity or a timestamp that goes backwards raises `OpenXrError` and leaves
  the state untouched; call `release(t)` as the fail-safe.
* Float values outside [0, 1] are clamped. The spec page for `XrActionStateFloat` does not
  state a range, so 0..1 is an assumption for trigger-like values.

`ClickTap` turns a click into one `TAP` per press; holding the button, or a runtime that
re-sends `True`, does not tap again.

### Time

`XrTime` is a signed 64-bit count of nanoseconds since a **runtime-chosen epoch**; zero
and negative values are invalid. The wire layer accepts device timestamps up to about
1e9 s, and a runtime whose epoch is the Unix epoch is already at 1.7e9 s. So:

```python
base = XrTimeBase()                       # one per XR session
t = base.to_seconds(xr_time_ns)           # small, non-negative device seconds
desktop_t = clock.map(t, desktop_now_s)   # wire.ClockMap anchors it to the desktop clock
```

`xr_time_to_seconds` is the exact absolute conversion for runtimes with a small epoch
(for example time since boot); it refuses values the wire layer would refuse. Call
`XrTimeBase.reset()` together with `ClockMap.reset()` when the XR session restarts.

For gaze, stamp the sample with the time the gaze was **measured**, not the frame's
predicted display time: `choose_gaze_time(sample_time_ns, display_time_ns)` uses
`XrEyeGazeSampleTimeEXT::time` and falls back to the display time when the runtime sets
it to 0, which the spec says it does when the sample time is unavailable.

## What was verified, and what was not

Checked against the public Khronos OpenXR 1.1 specification pages on 2026-10-30:

| Fact | Source |
|---|---|
| `XrPosef`: unit-quaternion orientation applied before the translation; runtime error beyond 1 % off unit | <https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrPosef.html> |
| `XrQuaternionf` fields `x, y, z, w` (floats) | <https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrQuaternionf.html> |
| Four location bits (orientation/position, valid/tracked) and their semantics | <https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrSpaceLocationFlagBits.html> |
| VIEW / LOCAL: "+Y up, +X to the right, and -Z forward"; STAGE: "+Y up" | <https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrReferenceSpaceType.html> |
| `XrTime`: int64 nanoseconds, runtime-chosen epoch, zero/negative invalid | <https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrTime.html> |
| `XrEyeGazeSampleTimeEXT::time`: may be in the future; 0 when unavailable | <https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrEyeGazeSampleTimeEXT.html> |
| 26 hand joints, values 0 to 25 | <https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrHandJointEXT.html> |
| Joint location: flags, pose in `baseSpace`, radius in metres, positive when position valid | <https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrHandJointLocationEXT.html> |

Read from search-result excerpts of the full specification (the single-page spec exceeded
the fetch size limit, so the sentences were not read in place): the eye-gaze pose axes
("+Y up, +X to the right, and -Z forward", not gravity-aligned) and its path
`/user/eyes_ext/input/gaze_ext/pose`; the profile paths `khr/simple_controller` and
`ext/hand_interaction_ext` and the `select/click`, `pinch_ext/value`, `grasp_ext/value`
and `aim_activate_ext/value` inputs; the aim pose being the one for objects out of reach.
Spec: <https://registry.khronos.org/OpenXR/specs/1.1/html/xrspec.html>.

**Unverified; do not rely on these without checking the spec:**

* the numeric flag-bit values and the numeric `XrReferenceSpaceType` values;
* that an aim pose points along -Z as a spec statement (it is the convention);
* the range of `XrActionStateFloat::currentState`, and that an inactive action reports 0;
* the `pinch_ext/pose` and `poke_ext/pose` paths and the pinch pose's definition;
* which runtimes actually grant which extensions on which devices. Forum reports say
  support varies and the support flags can be wrong on some runtimes; query the runtime,
  never assume. See also the device profiles in `yazses.xr.devices`, which keep unknown
  as unknown.

## Caveats

* **Synthetic only.** The tests build every number by hand or by property generator.
  No real gaze, hand or audio data was used, and none should be committed.
* **Not wired.** Nothing constructs these functions in an installed YazSes. There is no
  transport for companion frames yet.
* **Privacy.** Gaze and hand data are sensitive. The adapter keeps raw samples in memory
  only, for a short retention window, and never writes them to disk; see the privacy model
  in the [main guide](xr-voice-input.md).
* **Eye tracking is optional in OpenXR.** `XR_EXT_eye_gaze_interaction` is an extension a
  runtime may not offer, and a headset may have no eye tracker at all. A companion must
  fall back to head or hand rays when gaze is absent.
* **Thresholds are not measurements.** Every default (hysteresis levels, pinch gap range,
  untracked confidence) was chosen for synthetic tests and needs measuring on a real
  device before it is trusted.
