"""Meeting Mode — hands-free continuous capture + hybrid speaker diarization.

ADR-v2-127 (live meeting mode) + ADR-v2-128 (on-device minutes). Meeting mode records a
whole meeting without hold-to-talk, streams a rolling transcript for the status view, and
at *stop* runs an accurate batch diarization post-pass over the full recording — reusing
the ADR-v2-125 ``recimport`` cores — then optionally generates minutes with a local LLM.

Layering (heavy backends injected; pure cores dependency-free and unit-tested):
- ``store``     — meeting-folder read/write/list + post-hoc ``relabel`` (pure re-render).
- ``segmenter`` — continuous-audio → utterance chunks via a VAD predicate (pure).
- ``session``   — recording lifecycle: streams chunks to a WAV sink, tracks elapsed.
- ``finalize``  — batch pipeline at stop (wraps ``recimport.pipeline.transcribe_file``).
- ``notes``     — speaker-aware minutes via map-reduce + a local LLM (ADR-v2-128).
"""
