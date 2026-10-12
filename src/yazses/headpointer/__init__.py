"""Head-Pointer — hands-free cursor via head pose (ADR-v2-052).

Move and click the mouse by head tilt, paired with voice for a fully hands-free desktop. Three
layers, outermost last:

* ``pointer`` — the pure pose→cursor mapping + dwell-click state machine.
* ``controller`` — the pure runtime state machine (freshness, recenter, pause/clutch, dwell
  arming, the global safety gate) that turns a ``HeadPoseSignal`` into ``PointerSink`` calls.
* ``runtime`` — the thin shell that leases the shared camera (``perception/``), polls it and
  answers the ``yazses headpointer`` commands.

This package opens no camera and calls no platform API: the camera is the single-owner
perception source and the pointer is a ``PointerSink`` behind the platform factory. OFF by
default.
"""
