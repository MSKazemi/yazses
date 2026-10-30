"""XR voice-input adapter (pure) — headset/glasses observations in, grounded targets out.

ADR-025 keeps OpenXR and friends *outside* the Grounded Interaction Kernel: a spatial
device may only enter as observations, never define the kernel. This package is that
adapter. It has no OpenXR, Unity or network dependency — a companion app on the
headset (or phone) sends already-sampled rays and gestures over the existing paired
bridge (ADR-v2-013), and everything here is plain arithmetic on those numbers.

Not yet wired into the daemon: there is no ``[xr]`` config section and no CLI command, so
nothing here runs in an installed YazSes. The wiring will be off by default.
"""
