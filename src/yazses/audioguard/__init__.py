"""Ambient Audio-Event Guard (ADR-v2-061).

Auto-pause/alert when an interrupting real-world sound is heard. The ``policy`` module is the
pure label→policy map + debounce; the PANNs/SELD sound-event classifier is lazy behind a
``soundawareness`` extra. Frames stay in-RAM. OFF by default.
"""
