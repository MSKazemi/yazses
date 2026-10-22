"""AT-SPI Voice Pilot — accessibility-tree desktop control (ADR-v2-007).

Voice-drive the desktop via the accessibility tree ("click Save", "toggle dark
mode") — element labels + roles + actions only, never a screenshot (honours
ADR-011). ``plan`` is the pure command parser, label matcher and act-or-confirm
decision; ``service`` joins it to the platform's accessibility backend
(``platform/linux/atspi_tree.py`` over ``pyatspi``, Linux-only, from system
packages), which is built only on the first pilot phrase. OFF by default.
"""
