"""Neural-codec ultra-low-latency streaming STT (ADR-v2-022).

Route decoding to a streaming-native neural-codec engine (Kyutai STT + the Mimi codec,
~80 ms latency) when enabled, else keep the default faster-whisper. This package's
``select`` module is the pure engine-selection decision; the codec engine is lazy behind
the ``codec`` extra and dormant unless enabled + installed. OFF by default.
"""
