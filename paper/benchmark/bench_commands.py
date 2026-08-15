"""Command-grammar accuracy: precision on commands, false-positive rate on dictation.

Runs the shipping Tier-1 regex classifier (yazses.commands.grammar.classify) over two
existing fixtures:
- command_phrases.json  -> should classify as the expected command action (precision)
- dictation_corpus.txt  -> plain prose that must NOT be classified as a command (FPR)

Also times the classifier per call (the eval plan's <=5 ms/call target).
"""
from __future__ import annotations

import json
import time

from _common import REPO_ROOT, percentile

FIX = REPO_ROOT / "tests" / "fixtures" / "commands"


def run() -> dict:
    from yazses.commands.grammar import IntentType, classify

    phrases = json.loads((FIX / "command_phrases.json").read_text())
    dictation_lines = [
        ln.strip()
        for ln in (FIX / "dictation_corpus.txt").read_text().splitlines()
        if ln.strip()
    ]

    # --- Precision on the command set ---
    action_hits = 0
    intent_as_command = 0  # classified as any non-DICTATE intent
    misfires = []
    for item in phrases:
        res = classify(item["phrase"])
        if res.intent != IntentType.DICTATE:
            intent_as_command += 1
        if res.action == item["expected_action"]:
            action_hits += 1
        else:
            misfires.append(
                {
                    "phrase": item["phrase"],
                    "expected": item["expected_action"],
                    "got": res.action,
                    "intent": res.intent.value,
                }
            )
    n_cmd = len(phrases)

    # --- False positives on dictation ---
    false_positives = []
    for line in dictation_lines:
        res = classify(line)
        if res.intent != IntentType.DICTATE:
            false_positives.append({"text": line, "got": res.action})
    n_dict = len(dictation_lines)

    # --- Per-call runtime ---
    sample = [p["phrase"] for p in phrases] + dictation_lines
    for s in sample[:50]:  # warmup
        classify(s)
    times_ms = []
    for _ in range(20):
        for s in sample:
            t0 = time.perf_counter()
            classify(s)
            times_ms.append((time.perf_counter() - t0) * 1000.0)

    out = {
        "config": {
            "command_fixture": "tests/fixtures/commands/command_phrases.json",
            "dictation_fixture": "tests/fixtures/commands/dictation_corpus.txt",
            "n_command_phrases": n_cmd,
            "n_dictation_lines": n_dict,
        },
        "precision": {
            "action_accuracy_pct": round(100 * action_hits / n_cmd, 1),
            "classified_as_command_pct": round(100 * intent_as_command / n_cmd, 1),
            "action_hits": action_hits,
            "misfires": misfires,
        },
        "false_positive": {
            "false_positive_rate_pct": round(100 * len(false_positives) / n_dict, 2),
            "false_positives": false_positives,
        },
        "runtime": {
            "per_call_median_ms": round(percentile(times_ms, 50), 4),
            "per_call_p95_ms": round(percentile(times_ms, 95), 4),
            "n_calls": len(times_ms),
        },
    }
    print(
        f"[commands] action-accuracy={out['precision']['action_accuracy_pct']}%  "
        f"as-command={out['precision']['classified_as_command_pct']}%  "
        f"FPR={out['false_positive']['false_positive_rate_pct']}%  "
        f"per-call median={out['runtime']['per_call_median_ms']}ms",
        flush=True,
    )
    return out


if __name__ == "__main__":
    from _common import write_result

    write_result("commands", run())
