"""Camera selection: see the cameras, pick one, remember the pick (#924).

Pure logic lives in :mod:`yazses.camera.devices`; the OS enumeration sits behind the
``CameraEnumerator`` Protocol in ``yazses.platform.base``. Nothing here opens a camera.
"""
