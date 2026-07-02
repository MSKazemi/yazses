"""Spoken Math → LaTeX (ADR-v2-032).

Dictate math, inject LaTeX. The ``latex`` module is the pure grammar for the common
vocabulary + templates (greek, operators, integral/sum, squared, square root, superscripts);
arbitrary nested expressions route to a deferred MathSpeech model behind the ``mathspeech``
extra. OFF by default.
"""
