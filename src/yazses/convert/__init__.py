"""Voice Unit Conversion (ADR-v2-056).

Evaluate a spoken unit conversion inline ("twenty miles in kilometers" → "32.19 km"). The
``units`` module is the pure, dependency-free factor table + temperature formulae; the full pint
registry + offline currency snapshot are deferred behind the ``units`` extra. OFF by default.
"""
