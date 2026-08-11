#!/usr/bin/env python3
"""The review queue and the claim ledger — who is waiting on whom.

    uv run python scripts/campaign_queue.py             # the review queue
    uv run python scripts/campaign_queue.py --claims    # claims, and which have lapsed
    uv run python scripts/campaign_queue.py --json

Two questions this answers that GitHub's own UI does not:

**Who is actually waiting?** A pull request where the maintainer spoke last is waiting on
the contributor. One where the contributor spoke last is waiting on us, and that is the
only kind that damages anything. `scripts/inbox.py` already finds those; this orders them
by how long a person has been waiting, weighted so a first-time contributor's first pull
request does not sit behind routine work.

**Which claims have lapsed?** Someone says they are taking a task and then life happens.
Without expiry the task is locked forever and nobody else will touch it. With expiry it
returns to the pool. **Expiry is not a punishment and must never be framed as one** — the
message says the task is free again, thanks them, and leaves their branch alone.

Read-only. No writes, no comments posted, no state stored anywhere but GitHub.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from campaign_stats import REPO, _get, is_bot  # noqa: E402

from campaign import load_tasks  # noqa: E402

#: "claiming APP-014", "I'll take MIC-003", "claim: VEC-CORE-001"
CLAIM_RE = re.compile(
    r"\b(?:claim(?:ing|ed|s)?|taking|i'?ll take)\b[:\s]*([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)",
    re.I,
)

#: How long a claim holds a task before it returns to the pool. A schema-only record is a
#: single sitting; bounded code deserves a working week.
CLAIM_TTL = {"L0": timedelta(hours=48), "L1": timedelta(hours=48), "L2": timedelta(days=7),
             "L3": timedelta(days=7)}

#: A first pull request is the one most likely to be abandoned in silence, so it sorts up.
FIRST_PR_WEIGHT = 2.0
RISK_WEIGHT = {"L0": 1.0, "L1": 1.0, "L2": 1.3, "L3": 1.6}
EST_REVIEW_MINUTES = {"L0": 4, "L1": 7, "L2": 15, "L3": 30}


def parse_claims(comments: list[dict], known_ids: set[str]) -> list[dict]:
    """Claims found in issue comments. Later comments win for the same person+task."""
    out: dict[tuple[str, str], dict] = {}
    for c in comments:
        who = (c.get("user") or {}).get("login", "")
        if not who or is_bot(who):
            continue
        for m in CLAIM_RE.finditer(c.get("body") or ""):
            task_id = m.group(1).upper()
            if task_id not in known_ids:
                continue  # a stray token that merely looks like an id
            out[(who, task_id)] = {
                "task_id": task_id,
                "who": who,
                "at": c.get("created_at", ""),
            }
    return sorted(out.values(), key=lambda c: (c["task_id"], c["who"]))


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def lapsed_claims(claims: list[dict], tasks: dict[str, dict], now: datetime) -> list[dict]:
    """Claims past their TTL, with how long ago they lapsed."""
    out: list[dict] = []
    for claim in claims:
        task = tasks.get(claim["task_id"])
        at = _parse_ts(claim["at"])
        if task is None or at is None:
            continue
        ttl = CLAIM_TTL.get(task["risk"], timedelta(days=7))
        if now - at > ttl:
            out.append({**claim, "lapsed_hours": round((now - at - ttl).total_seconds() / 3600, 1)})
    return out


def review_priority(pr: dict, *, now: datetime) -> float:
    """How urgently a human should look at this. Higher sorts first.

    Deliberately divided by expected review minutes: two cheap reviews that unblock two
    people beat one expensive one, when both have waited the same time.
    """
    updated = _parse_ts(pr.get("updated_at", "")) or now
    waiting_hours = max((now - updated).total_seconds() / 3600, 0.1)
    risk = pr.get("risk", "L1")
    weight = FIRST_PR_WEIGHT if pr.get("first_pr") else 1.0
    return waiting_hours * weight * RISK_WEIGHT.get(risk, 1.0) / EST_REVIEW_MINUTES.get(risk, 7)


def render_queue(prs: list[dict], *, now: datetime) -> str:
    if not prs:
        return "✓ review queue empty — nobody is waiting on us.\n"
    ranked = sorted(prs, key=lambda p: review_priority(p, now=now), reverse=True)
    lines = [
        f"# Review queue — {len(ranked)} waiting on a human",
        "",
        "| PR | author | risk | waiting | first PR? |",
        "|---|---|---|---:|---|",
    ]
    for pr in ranked:
        updated = _parse_ts(pr.get("updated_at", "")) or now
        hours = (now - updated).total_seconds() / 3600
        lines.append(
            f"| #{pr.get('number')} | @{(pr.get('user') or {}).get('login', '?')} | "
            f"{pr.get('risk', '?')} | {hours:.0f}h | {'yes' if pr.get('first_pr') else ''} |"
        )
    return "\n".join(lines) + "\n"


def render_claims(lapsed: list[dict], total: int) -> str:
    if not lapsed:
        return f"✓ {total} claim(s), none lapsed.\n"
    lines = [
        f"# Lapsed claims — {len(lapsed)} of {total}",
        "",
        "These tasks are free again. This is not a failure on anyone's part: say thank you,",
        "leave their branch and any PR untouched, and let the task return to the pool.",
        "",
    ]
    for c in lapsed:
        lines.append(f"  {c['task_id']:<28} @{c['who']} — lapsed {c['lapsed_hours']}h ago")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--claims", action="store_true", help="report claims instead of the queue")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    tasks = {t["id"]: t for t in load_tasks()}

    try:
        if args.claims:
            comments = _get(f"/repos/{REPO}/issues/comments?per_page=100")
            claims = parse_claims(comments, set(tasks))
            lapsed = lapsed_claims(claims, tasks, now)
            print(json.dumps(lapsed, indent=2) if args.json else render_claims(lapsed, len(claims)), end="")
            return 0
        prs = [p for p in _get(f"/repos/{REPO}/pulls?state=open&per_page=100")]
        print(json.dumps(prs, indent=2, default=str) if args.json else render_queue(prs, now=now), end="")
        return 0
    except Exception as exc:  # noqa: BLE001 - any network/parse failure degrades the same way
        print(f"⚠ could not reach the GitHub API ({type(exc).__name__}) — no queue data.", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
