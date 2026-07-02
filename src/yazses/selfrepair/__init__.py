"""Mid-Utterance Self-Repair (ADR-v2-058).

Apply explicit in-burst corrections before injection ("email Sarah, no I mean Sara" → "email
Sara"). The ``repair`` module is the pure editing-term grammar + span replacement; the SpeechLLM
span classifier for open-ended repairs is deferred. OFF by default.
"""
