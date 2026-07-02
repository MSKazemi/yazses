"""Per-Language Auto Model Switching (ADR-v2-072).

Detect the spoken language and hot-swap to a language-specialized model + ITN. The ``route``
module is the pure selector; the extra model files and the live LID call are deferred. OFF by
default.
"""
