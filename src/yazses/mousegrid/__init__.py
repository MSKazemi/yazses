"""Voice Mouse Grid — pointer control by voice (ADR-v2-030).

A Talon-style overlaid grid to drive the cursor and click by voice ("three… seven… click")
where no accessibility tree exists — the universal pixel-level fallback to AT-SPI Pilot and
Gaze. The ``grid`` module is the pure subdivision math; rendering + clicking reuse the
existing overlay and injector. OFF by default.
"""
