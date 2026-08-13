"""Activation sources — how something tells YazSes to act.

A source may simply trigger (a key, an EMG squeeze), or it may carry an
**intent**: a label plus a confidence, drawn from a vocabulary it declares up
front. See :mod:`yazses.activation.intent` for the seam and
:mod:`yazses.activation.confirm` for the policy that decides whether a decoded
intent is acted on or confirmed first.
"""
