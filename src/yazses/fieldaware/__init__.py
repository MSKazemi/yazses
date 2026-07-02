"""Field-Aware Dictation — output shaped by the focused control (ADR-v2-047).

Read the accessibility role of the focused widget and reshape dictation output: number fields →
digits, search boxes → no trailing period, password fields → refuse. The ``profile`` module is
the pure role→profile map + apply logic; the role read comes from the platform accessibility
layer. OFF by default.
"""
