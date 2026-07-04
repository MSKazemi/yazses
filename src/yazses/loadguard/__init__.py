"""LoadGuard — cognitive-load-aware guardrails (ADR-v2-121).

Rising cognitive-load speech signals (pauses, fillers, slowed rate, self-corrections) widen
confirmations and defer risky actions. The ``policy`` module is the pure estimator + policy;
signal extraction reuses existing pipeline metrics. OFF by default.
"""
