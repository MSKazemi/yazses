"""HatSelect — spoken structural token addressing (ADR-v2-115).

Label every visible token and resolve structural edit references by voice (Cursorless-style). The
``labels`` module is the pure labeler + resolver + planner; the editor bridge is the only I/O. OFF by
default.
"""
