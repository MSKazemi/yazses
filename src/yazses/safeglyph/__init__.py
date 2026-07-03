"""SafeGlyph — homoglyph/confusable hazard detection (ADR-v2-123).

Flag Unicode confusables and invisible characters in dictated identifiers/URLs/secrets before they
are injected (Cyrillic "а" vs Latin "a"). The ``confusables`` module is the pure UTS-39-subset
scanner + ASCII normalizer. OFF by default.
"""
