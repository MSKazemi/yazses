---
title: XR engine coordinate conversion (Unity, Unreal, Godot)
description: How a companion app built in Unity, Unreal Engine or Godot maps its positions, rays, quaternions and panels onto the YazSes XR adapter's single frame, with a conversion table per engine, the mistakes that produce a silently mirrored pointing ray, and illustration-only pseudo-code. A library with synthetic tests only; not connected to the daemon.
---

# XR engine coordinate conversion

> **Status: a library, not a feature you can turn on.** `yazses.xr.engines` is pure
> arithmetic, tested on **synthetic** numbers only (generated scenes and hand-computed
> examples). It is **not connected to the daemon**, has **no config key and no command**,
> and no companion app exists. Nothing here was measured on a real headset, and no
> accuracy or latency figure is claimed. This page is for someone writing a companion app
> who needs the numbers to line up. See [XR voice input](xr-voice-input.md) for the rest of
> the adapter.

## Why this exists

The adapter works in one frame: **right-handed, +X right, +Y up, -Z forward, metres,
radians** (the OpenXR convention). Game engines each pick their own, and two of the three
common ones are **left-handed**. Feed their numbers in unconverted and nothing fails: the
ray is simply mirrored, so dictation lands in the panel on the other side of you. The
module `yazses.xr.engines` converts positions, directions, quaternions, rays and panel
definitions in both directions, and refuses malformed input with a `ValueError` instead of
guessing.

Verified against each engine's public documentation on 2026-10-30; the one item the
documentation did not settle is marked **unverified**.

## Conversion table

Canonical frame for comparison: right = +X, up = +Y, forward = -Z, metres.

| | Unity | Unreal Engine | Godot |
|---|---|---|---|
| Handedness | left | left | right |
| Right | +X | +Y | +X |
| Up | +Y | +Z | +Y |
| Forward | +Z | +X | -Z (`Vector3.FORWARD`) |
| Unit | 1 = 1 m | 1 = **1 cm** | 1 = 1 m |
| Position to canonical `(x, y, z)` | `(x, y, -z)` | `0.01 * (y, z, -x)` | unchanged |
| Direction to canonical | `(x, y, -z)` | `(y, z, -x)` (no scale) | unchanged |
| Quaternion to canonical `(x, y, z, w)` | `(-x, -y, z, w)` | `(-y, -z, x, w)` | unchanged |
| Euler angles | degrees; applied about z, then x, then y | `FRotator`: pitch, yaw, roll in degrees; sign convention **unverified** | order is explicit in the call; default `YXZ`, radians |
| Matrix to quaternion | axes are the **columns**: `transform.right / up / forward` | not covered here | `Basis(x, y, z)` takes the **columns** |

How the quaternion row is derived (it is the easy one to get wrong): write the axis
change as a signed permutation `M`. A rotation `R` in the engine becomes `M R M^-1` in the
canonical frame, and its axis is a pseudovector, so the vector part maps to
`det(M) * M * v`, not `M * v`. `det(M)` is `-1` for Unity and Unreal and `+1` for Godot.
`w` never changes. For Unity that gives `(-x, -y, z, w)`, which matches what Meta's
Unity SDK documents for its own handedness flip (`ToFlippedZQuatf`: "negates the X and Y
components"; `ToFlippedZVector3f`: "negates the Z component").

Sources:
[Unity: Quaternion and Euler rotations](https://docs.unity.com/en-us/engine/6000.3/manual/working-with-gameobjects/gameobject-fundamentals/rotation-orientation/quaternion-and-euler-rotations-in-unity),
[Unreal: Coordinate System and Spaces](https://dev.epicgames.com/documentation/unreal-engine/coordinate-system-and-spaces-in-unreal-engine?lang=en-US),
[Unity to Unreal FAQ (units)](https://dev.epicgames.com/documentation/en-us/unreal-engine/unity-to-unreal-engine-frequently-asked-questions-faq),
[Godot introduction to 3D](https://docs.godotengine.org/en/stable/tutorials/3d/introduction_to_3d.html),
[Godot Vector3](https://docs.godotengine.org/en/stable/classes/class_vector3.html),
[Godot Basis](https://docs.godotengine.org/en/stable/classes/class_basis.html),
[Meta OVRPose](https://developers.meta.com/horizon/reference/unity/v74/struct_o_v_r_pose),
[Meta OVRExtensions](https://developers.meta.com/horizon/reference/unity/v83/class_o_v_r_extensions).

### Meta Quest

Quest is not a fourth frame. A Unity app for Quest uses the Unity column; an Unreal app
uses the Unreal column. The native plugin underneath is right-handed and Meta's Unity code
flips z between the two, which is the Unity rule above. What is **unverified** here is which
local axis a particular controller or hand pointer pose points along (Unity `+Z` is the
engine's forward, but check the axis your SDK documents for that pose and pass it as
`local_forward`). Tracking-origin choice (floor level or eye level) shifts the height of
every position; the conversion does not change it.

## The panel: why `right = up x normal` needs care

A panel has a `normal` (toward the viewer, the readable face), an `up`, and a size. The
adapter's ray cast reads panel coordinates as `u = 0.5 + dot(p - center, right) / width` with
`right = up x normal`. In a right-handed frame that is the viewer's right. In a left-handed
engine the same arithmetic on the raw numbers gives the **opposite** side, so:

- convert `normal` and `up` as **directions** (`panel_to_canonical`), never by hand-crossing
  engine numbers, and
- when you need the viewer's right in engine axes, call `panel_right` (it is
  `normal x up` in Unity and Unreal, `up x normal` in Godot).

Sizes are converted too: an Unreal panel 200 units wide is 2 m wide.

## Common mistakes

1. **Using the engine's numbers as if they were already canonical.** The tested example: a
   Unity panel 5 m ahead, a ray aimed 0.5 m to the right. Raw, the hit reads `u = 0.25`;
   converted, `u = 0.75`. No error is raised.
2. **Negating z of a Unity quaternion.** Negate x and y (`(-x, -y, z, w)`); the vector part
   is a pseudovector. Negating only z turns a right turn into a left turn.
3. **Forgetting Unreal's centimetres.** Positions *and* panel sizes. Directions are never
   scaled.
4. **Scaling a direction.** A cm-to-m factor on a direction breaks unit length; the
   converter rejects non-unit directions, so this surfaces as an error, not a bad ray.
5. **Rows instead of columns.** `quat_from_basis` wants the axes as columns (Godot
   `Basis(x, y, z)`, Unity `transform.right / up / forward`). Passing rows yields the
   inverse rotation, which turns the other way.
6. **A mirrored basis.** A transform with a negative scale on one axis is not a rotation and
   has no quaternion; `quat_from_basis` raises.
7. **Assuming every engine's "forward" is the camera's.** Godot cameras look down -Z, but
   imported Godot models face +Z (`MODEL_FRONT`). Which local axis a panel mesh shows its
   readable face on depends on the asset (a Unity quad or world-space canvas is readable
   from its local -Z side, a Godot quad from +Z; both **unverified** here): `panel_from_pose`
   makes you state it.
8. **Non-unit quaternions or directions.** Single-precision engine floats drift by about
   1e-7; the converters accept up to 1e-3 and return an exactly unit value, and refuse
   anything further out (a position passed as a direction, a half-built quaternion).
9. **Mixing Euler orders.** Unity applies z, then x, then y. Godot's default is `YXZ` and
   the order is part of the call. `unreal_rotator_to_quat` states the sign convention it
   assumes; build an `FQuat` directly if you need certainty.

## Using the module

The functions are pure and total: every one returns a valid value or raises `ValueError`
(NaN, infinity, magnitudes beyond 1e9 engine units, wrong types, zero or non-unit
directions, non-unit quaternions, mirrored bases, an unknown engine). Nothing is clamped
quietly, and none of them touches the network or the clock.

| Function | Does |
|---|---|
| `position_to_canonical`, `position_from_canonical` | positions (Unreal cm to m and back) |
| `length_to_canonical`, `length_from_canonical` | sizes such as panel width |
| `direction_to_canonical`, `direction_from_canonical` | unit directions, axes only |
| `ray_to_canonical`, `ray_from_canonical` | an origin plus a direction |
| `quat_to_canonical`, `quat_from_canonical` | rotations (pseudovector rule) |
| `quat_rotate`, `quat_from_basis` | rotate a vector; matrix columns to quaternion |
| `unity_euler_to_quat`, `unreal_rotator_to_quat` | degrees to a `Quat` in the engine frame |
| `ray_from_pose` | a pose (position plus rotation) to a pointing ray |
| `panel_to_canonical`, `panel_from_canonical`, `panel_from_pose`, `panel_right` | panels |

### Illustration only: companion-side sketch

The blocks below are **pseudo-code to show the shape of the calls**. They are not shipped,
not tested as written, and no companion app exists. Names on the engine side are
placeholders.

```text
# ILLUSTRATION ONLY - Unity companion (C#-like pseudo-code), one frame of data
head   = camera.position, camera.rotation        # engine frame, metres
ray    = engines.ray_from_pose(head.position, head.rotation, UNITY)
panel  = engines.panel_from_pose("notes", quad.position, quad.rotation,
                                 width, height, UNITY,
                                 normal_local=(0, 0, -1), up_local=(0, 1, 0))
# send ray and panel to the desktop through the wire format
```

```text
# ILLUSTRATION ONLY - Unreal companion (Blueprint or C++ like pseudo-code)
# Unreal reports centimetres. The converter divides them down; do not do it twice.
origin = camera.location                  # cm
q      = camera.rotation.quaternion()     # FQuat, Unreal frame
ray    = engines.ray_from_pose(origin, q, UNREAL)
```

```text
# ILLUSTRATION ONLY - Godot companion (GDScript-like pseudo-code)
b = node.global_transform.basis           # columns are x, y, z
q = engines.quat_from_basis(b.x, b.y, b.z)
ray = engines.ray_from_pose(node.global_position, q, GODOT)
```

### What the tests prove

For each engine the test suite builds an engine-frame scene (panel, ray, aim point), casts
it with a small ray cast written separately in the engine's own frame, converts the same
scene, casts it through `yazses.xr.raycast`, and requires the same `u`, `v` and distance
(distance in metres for Unreal) to within floating-point tolerance. It also checks that
rotating a vector commutes with converting the quaternion, and that Unity's quaternion rule
equals Meta's documented flip. All of that is synthetic geometry, not device data.

## What is not covered

- Android XR and visionOS handling stay in `yazses.xr.conventions`, where they are marked
  as unconfirmed assumptions.
- The Unreal `FRotator` sign convention is unverified against the public pages.
- Left-up-forward frames (Unreal Editor for Fortnite and Verse) are a different convention
  and are not handled.
- Which axis a given headset's controller pointer pose points along is not settled here.
- Nothing is transported: there is no companion app and no connection to the daemon.
