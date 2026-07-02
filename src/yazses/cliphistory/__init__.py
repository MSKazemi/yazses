"""Clipboard-History by Voice (ADR-v2-060).

Recall recent copies by spoken index or description ("paste the second thing I copied"). The
``history`` module is the pure ring buffer + spoken-reference resolver; semantic recall via an
on-device embedding is deferred. Buffer lives in local process memory. OFF by default.
"""
