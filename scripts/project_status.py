#!/usr/bin/env python3
"""Move an issue's card on the YazSes project board when someone is assigned.

GitHub's built-in project workflows move a card when an issue is closed, reopened or
linked to a pull request, but not when it is assigned. Assignment is how a contributor
claims an issue, so without this the board's "In Progress" column misses exactly the work
people have said they are doing. Run by `.github/workflows/project-status.yml` on
`issues: [assigned, unassigned]`.

The rule, decided by `target_status` from the issue's live state (not the event payload,
so a quick assign-then-unassign settles on what is true now):

- an open issue with an assignee moves from Todo (or no status) to In Progress;
- an open issue whose last assignee left moves from In Progress back to Todo, unless an
  open pull request still references it -- that PR is why it is in progress;
- anything else is left alone. A card someone moved by hand is never dragged back.

Exit 0 with a notice when `GH_TOKEN` is empty: the repository's own `GITHUB_TOKEN` cannot
write to a user-owned project, so the workflow needs a personal token in the
`PROJECT_TOKEN` secret, and until the owner adds one this must not turn the run red.

Usage (what the workflow runs):
    GH_TOKEN=... python3 scripts/project_status.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Any

API = "https://api.github.com/graphql"
TODO = "Todo"
IN_PROGRESS = "In Progress"

LOOKUP = """
query($owner: String!, $number: Int!, $issue: ID!) {
  user(login: $owner) {
    projectV2(number: $number) {
      id
      field(name: "Status") {
        ... on ProjectV2SingleSelectField { id options { id name } }
      }
    }
  }
  node(id: $issue) {
    ... on Issue {
      number
      state
      assignees { totalCount }
      closedByPullRequestsReferences(first: 1, includeClosedPrs: false) { totalCount }
      projectItems(first: 50) {
        nodes {
          id
          project { id }
          fieldValueByName(name: "Status") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
        }
      }
    }
  }
}
"""

ADD_ITEM = """
mutation($project: ID!, $content: ID!) {
  addProjectV2ItemById(input: {projectId: $project, contentId: $content}) { item { id } }
}
"""

SET_STATUS = """
mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $project, itemId: $item, fieldId: $field,
    value: {singleSelectOptionId: $option}
  }) { projectV2Item { id } }
}
"""


def target_status(
    *, is_open: bool, assignees: int, open_linked_prs: int, current: str | None
) -> str | None:
    """The status the card should move to, or None to leave it where it is."""
    if not is_open:
        return None
    if assignees > 0:
        return IN_PROGRESS if current in (None, TODO) else None
    if current == IN_PROGRESS and open_linked_prs == 0:
        return TODO
    return None


def graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return payload["data"]


def main() -> int:
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        print(
            "::notice::PROJECT_TOKEN is not set, so the project board was not updated. "
            "Add a personal token with the `project` scope as that secret to enable this."
        )
        return 0

    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as fh:
        event = json.load(fh)
    issue_id = event["issue"]["node_id"]
    owner = os.environ["PROJECT_OWNER"]
    number = int(os.environ["PROJECT_NUMBER"])

    data = graphql(token, LOOKUP, {"owner": owner, "number": number, "issue": issue_id})
    project = data["user"]["projectV2"]
    issue = data["node"]
    options = {o["name"]: o["id"] for o in project["field"]["options"]}
    item = next(
        (n for n in issue["projectItems"]["nodes"] if n["project"]["id"] == project["id"]),
        None,
    )
    current = (item.get("fieldValueByName") or {}).get("name") if item else None

    target = target_status(
        is_open=issue["state"] == "OPEN",
        assignees=issue["assignees"]["totalCount"],
        open_linked_prs=issue["closedByPullRequestsReferences"]["totalCount"],
        current=current,
    )
    if target is None:
        print(f"#{issue['number']}: status {current!r} left unchanged")
        return 0

    if item is None:
        # Auto-add may not have run yet; adding here is idempotent if it has.
        added = graphql(token, ADD_ITEM, {"project": project["id"], "content": issue_id})
        item = added["addProjectV2ItemById"]["item"]
    graphql(
        token,
        SET_STATUS,
        {
            "project": project["id"],
            "item": item["id"],
            "field": project["field"]["id"],
            "option": options[target],
        },
    )
    print(f"#{issue['number']}: status {current!r} -> {target!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
