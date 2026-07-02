"""Dictation Reflow — Voice Outliner (ADR-v2-038).

On command ("structure this"), rewrite the last monologue into a bulleted outline with action
items. The ``outline`` module is the pure discourse-marker heuristic; a higher-quality SLM
reflow is deferred behind the ``reflow`` extra (reuses the llm_cleanup guard). OFF by default.
"""
