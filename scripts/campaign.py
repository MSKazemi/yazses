#!/usr/bin/env python3
"""Task inventory for the contributor campaign — validator, generator, and schema.

A campaign task is a unit of contribution that one person can finish in one sitting,
that produces something the project actually consumes, and that a schema or a command
can check. The inventory lives in `campaign/tasks.json`; this module is the only thing
that decides whether a row in it is valid.

**Why the schema is generated rather than written.** The playbook asks for a
`task.schema.json`. A hand-written schema beside a hand-written validator is two sources
of truth that drift, and this repository has been bitten by exactly that shape more than
once — a registry entry that nothing reads, documentation that contradicts the code. So
`FIELD_SPEC` below is authoritative, `json_schema()` derives the JSON Schema from it, and
a test fails if the committed schema is stale. External tools get a real schema; there is
still only one place to change a rule.

**No new dependencies.** Validation is hand-rolled rather than using `jsonschema`,
because YazSes runs a deliberate 18-package base budget and campaign tooling is not a
reason to widen it.

Usage:

    uv run python scripts/campaign.py --check       # validate the inventory (CI gate)
    uv run python scripts/campaign.py --generate    # rewrite the generated artifacts
    uv run python scripts/campaign.py --stats       # print a one-screen summary
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN = ROOT / "campaign"
TASKS_JSON = CAMPAIGN / "tasks.json"
SCHEMA_JSON = CAMPAIGN / "schemas" / "task.schema.json"
OPEN_TASKS_MD = CAMPAIGN / "generated" / "open-tasks.md"
DASHBOARD_MD = CAMPAIGN / "generated" / "dashboard.md"
STATS_JSON = CAMPAIGN / "generated" / "stats.json"
#: The same two pages, published on the docs site — that is where readers actually arrive.
#: Generated rather than copied, so a test catches them drifting from the inventory.
DOCS_TASKS_MD = ROOT / "docs" / "contribute" / "tasks.md"
DOCS_BUILT_MD = ROOT / "docs" / "contribute" / "built.md"
DOCS_FINDER_MD = ROOT / "docs" / "contribute" / "find.md"

# ── The contract ──────────────────────────────────────────────────────────────

#: Task families. Each maps to a durable output the project consumes; a family that
#: stops producing something useful gets retired, however well it converts.
FAMILIES = (
    "compatibility",
    "app-profile",
    "localization",
    "contract-vector",
    "feature-wiring",
    "measurement",
    "docs",
    "packaging",
    "qa-fixture",
    "security-privacy",
)

#: Risk lanes. These decide who may approve, not how hard the work is.
#: L3 is never advertised as a quick first contribution.
RISKS = ("L0", "L1", "L2", "L3")

#: Lifecycle. `draft` and `verified` are internal; only `open` may be advertised.
STATES = ("draft", "verified", "open", "claimed", "pr-open", "merged", "expired", "needs-work")

ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")

#: field -> (json type, required, description)
FIELD_SPEC: dict[str, tuple[str, bool, str]] = {
    "id": ("string", True, "Stable unique identifier, SCREAMING-KEBAB (COMPAT-GNOME-WAYLAND-001)."),
    "family": ("string", True, f"One of: {', '.join(FAMILIES)}."),
    "title": ("string", True, "What the contributor will do, in one line."),
    "value": ("string", True, "Why the project wants it. A task with no stated value is not open."),
    "risk": ("string", True, f"Review lane, one of: {', '.join(RISKS)}."),
    "minutes": ("integer", True, "Honest estimate for someone who has not seen the repo."),
    "skills": ("array", True, "Skills needed, e.g. ['python'], ['toml'], [] for none."),
    "requires": ("object", False, "Environment the contributor must actually have (os, desktop, app)."),
    "cloud_agent_ready": ("boolean", True, "True only if a container can produce the whole evidence."),
    "allowed_paths": ("array", True, "Globs the PR may touch. Preflight rejects anything else."),
    "validation": ("array", True, "Exact commands that decide whether the work is done."),
    "evidence": ("array", False, "What the human must observe and report; empty for pure-code tasks."),
    "state": ("string", True, f"Lifecycle, one of: {', '.join(STATES)}."),
    "source": ("string", False, "Where this task came from — an issue, a registry, a doc gap."),
}

MIN_MINUTES, MAX_MINUTES = 5, 480

#: `scripts/check-task.py` executes a task's `validation` commands on a contributor's own
#: machine. That makes `tasks.json` a code-execution surface: a pull request editing it
#: could otherwise run anything on anyone who validated their work before pushing. Commands
#: must therefore start with one of these prefixes, are never passed to a shell, and a
#: reviewer approving a change here is approving code that runs on other people's laptops.
ALLOWED_VALIDATION_PREFIXES = (
    "uv run python -m pytest ",
    "uv run python scripts/",
    "uv run ruff check ",
    "make ",
)

#: Shell metacharacters that would chain a second command past the prefix check.
_SHELL_METACHARS = (";", "&", "|", "$(", "`", ">", "<", "\n")


def validation_command_problem(cmd: str) -> str | None:
    """Why this validation command is not safe to run, or None if it is."""
    if not cmd.startswith(ALLOWED_VALIDATION_PREFIXES):
        return (
            f"validation command {cmd!r} does not start with an allowed prefix "
            f"{list(ALLOWED_VALIDATION_PREFIXES)} — check-task.py runs these on a "
            "contributor's machine, so the inventory is a code-execution surface"
        )
    found = [c for c in _SHELL_METACHARS if c in cmd]
    if found:
        return (
            f"validation command {cmd!r} contains shell metacharacter(s) {found} — "
            "commands are run without a shell, and chaining is how a prefix allowlist "
            "gets bypassed"
        )
    return None


def json_schema() -> dict[str, Any]:
    """Derive the JSON Schema from FIELD_SPEC so the two cannot disagree."""
    props: dict[str, Any] = {}
    for name, (jtype, _required, desc) in FIELD_SPEC.items():
        prop: dict[str, Any] = {"type": jtype, "description": desc}
        if name == "id":
            prop["pattern"] = ID_RE.pattern
        elif name == "family":
            prop["enum"] = list(FAMILIES)
        elif name == "risk":
            prop["enum"] = list(RISKS)
        elif name == "state":
            prop["enum"] = list(STATES)
        elif name == "minutes":
            prop["minimum"], prop["maximum"] = MIN_MINUTES, MAX_MINUTES
        elif jtype == "array":
            prop["items"] = {"type": "string"}
        props[name] = prop
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/MSKazemi/yazses/campaign/schemas/task.schema.json",
        "title": "YazSes campaign task",
        "description": (
            "Generated from FIELD_SPEC in scripts/campaign.py — edit that, not this file. "
            "A test fails if this copy is stale."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": [n for n, (_t, req, _d) in FIELD_SPEC.items() if req],
        "properties": props,
    }


# ── Validation ────────────────────────────────────────────────────────────────

_PY_TYPE = {"string": str, "integer": int, "array": list, "object": dict, "boolean": bool}


def validate_task(task: Any, *, index: int | None = None) -> list[str]:
    """Return every problem with one task. Empty list means valid."""
    where = f"task[{index}]" if index is not None else "task"
    if not isinstance(task, dict):
        return [f"{where}: expected an object, got {type(task).__name__}"]

    tid = task.get("id")
    where = f"task {tid!r}" if isinstance(tid, str) else where
    errors: list[str] = []

    unknown = sorted(set(task) - set(FIELD_SPEC))
    if unknown:
        errors.append(f"{where}: unknown field(s) {unknown} — add them to FIELD_SPEC or drop them")

    for name, (jtype, required, _desc) in FIELD_SPEC.items():
        if name not in task:
            if required:
                errors.append(f"{where}: missing required field {name!r}")
            continue
        value = task[name]
        # bool is a subclass of int in Python; an integer field must not accept True.
        if jtype == "integer" and isinstance(value, bool):
            errors.append(f"{where}: {name} must be an integer, got a boolean")
            continue
        if not isinstance(value, _PY_TYPE[jtype]):
            errors.append(f"{where}: {name} must be {jtype}, got {type(value).__name__}")
            continue

    if errors:  # further checks would just cascade off bad types
        return errors

    if not ID_RE.match(task["id"]):
        errors.append(
            f"{where}: id must be SCREAMING-KEBAB with at least one dash "
            f"(e.g. COMPAT-FEDORA-KDE-001), got {task['id']!r}"
        )
    if task["family"] not in FAMILIES:
        errors.append(f"{where}: family {task['family']!r} is not one of {list(FAMILIES)}")
    if task["risk"] not in RISKS:
        errors.append(f"{where}: risk {task['risk']!r} is not one of {list(RISKS)}")
    if task["state"] not in STATES:
        errors.append(f"{where}: state {task['state']!r} is not one of {list(STATES)}")
    if not MIN_MINUTES <= task["minutes"] <= MAX_MINUTES:
        errors.append(
            f"{where}: minutes={task['minutes']} outside {MIN_MINUTES}–{MAX_MINUTES}. "
            "A task longer than a sitting should be split."
        )
    for list_field in ("allowed_paths", "validation"):
        if not task[list_field]:
            errors.append(
                f"{where}: {list_field} is empty — an unbounded task cannot be preflighted "
                "and cannot be reviewed cheaply"
            )
        if not all(isinstance(x, str) and x.strip() for x in task[list_field]):
            errors.append(f"{where}: {list_field} must contain non-empty strings")
    if not task["value"].strip():
        errors.append(f"{where}: value is blank — state why the project wants this or drop it")

    for cmd in task["validation"]:
        problem = validation_command_problem(cmd)
        if problem:
            errors.append(f"{where}: {problem}")

    # The rule the playbook is most emphatic about, and the one an inventory generator
    # is most likely to get wrong: a machine cannot certify hardware or native language.
    if task["cloud_agent_ready"] and task["family"] in ("compatibility", "measurement"):
        errors.append(
            f"{where}: family {task['family']!r} needs evidence observed on a real machine, "
            "so cloud_agent_ready must be false"
        )
    if task["cloud_agent_ready"] and task["family"] == "localization":
        errors.append(
            f"{where}: localization needs a native speaker's judgement, "
            "so cloud_agent_ready must be false"
        )
    if task["risk"] == "L3" and task["state"] == "open":
        errors.append(
            f"{where}: L3 is architecture/security work and must not be advertised as an "
            "open first contribution — keep it 'draft' or 'verified'"
        )
    return errors


def validate_inventory(tasks: Any) -> list[str]:
    """Validate the whole inventory, including cross-task rules."""
    if not isinstance(tasks, list):
        return [f"tasks.json must contain a list, got {type(tasks).__name__}"]

    errors: list[str] = []
    for i, task in enumerate(tasks):
        errors.extend(validate_task(task, index=i))

    ids = [t["id"] for t in tasks if isinstance(t, dict) and isinstance(t.get("id"), str)]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"duplicate task id(s): {dupes} — ids are how claims and PRs are matched")
    return errors


def load_tasks(path: Path = TASKS_JSON) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


# ── Generated artifacts ───────────────────────────────────────────────────────

def stats(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    def tally(key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in tasks:
            out[t[key]] = out.get(t[key], 0) + 1
        return dict(sorted(out.items()))

    openable = [t for t in tasks if t["state"] == "open"]
    return {
        "total": len(tasks),
        "open": len(openable),
        "by_family": tally("family"),
        "by_risk": tally("risk"),
        "by_state": tally("state"),
        "no_setup_needed": sum(1 for t in openable if not t["skills"]),
        "cloud_agent_ready": sum(1 for t in openable if t["cloud_agent_ready"]),
        "hardware_required": sum(1 for t in openable if t.get("requires")),
        "review_minutes_if_all_merged": sum(
            {"L0": 4, "L1": 7, "L2": 15, "L3": 30}[t["risk"]] for t in openable
        ),
    }


def render_open_tasks(tasks: list[dict[str, Any]]) -> str:
    """The browsable list a contributor filters — the 'matcher', as a static file.

    Deliberately not a generated issue per row: 120 bot-filed issues would bury the
    human ones and read as spam, which is the failure mode the playbook names.
    """
    openable = sorted(
        (t for t in tasks if t["state"] == "open"),
        key=lambda t: (t["family"], t["minutes"], t["id"]),
    )
    s = stats(tasks)
    lines = [
        "<!-- GENERATED by scripts/campaign.py --generate. Do not edit by hand. -->",
        "# Open contributor tasks",
        "",
        f"**{s['open']} open** of {s['total']} in the inventory · "
        f"{s['no_setup_needed']} need no Python · "
        f"{s['cloud_agent_ready']} work in a browser container · "
        f"{s['hardware_required']} need your own machine.",
        "",
        "You do not need permission and nothing is assigned. Pick one, say so on the linked",
        "issue so nobody doubles up, and open the PR. A coding agent is welcome — you remain",
        "the author, and you are expected to have read every line you send.",
        "",
        "`Risk` is who reviews it, not how hard it is: **L0** schema-only, **L1** bounded",
        "docs/config, **L2** bounded code.",
        "",
    ]
    for family in FAMILIES:
        rows = [t for t in openable if t["family"] == family]
        if not rows:
            continue
        lines += [
            f"## {family} ({len(rows)})",
            "",
            "| Task | ID | Risk | Time | Needs | Validate with |",
            "|---|---|---|---|---|---|",
        ]
        for t in rows:
            needs = ", ".join(sorted((t.get("requires") or {}).values())) or (
                ", ".join(t["skills"]) or "a text editor"
            )
            lines.append(
                f"| {t['title']} | `{t['id']}` | {t['risk']} | {t['minutes']} min | "
                f"{needs} | `{t['validation'][0]}` |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_dashboard(tasks: list[dict[str, Any]]) -> str:
    """The public view: what this campaign has actually produced, by category.

    Deliberately counts *merged* work, not tasks published or people recruited. A
    dashboard of activity rather than output is how a campaign convinces itself it is
    working while producing nothing — so this shows zeros honestly until real work lands,
    and says so.
    """
    s = stats(tasks)
    merged = sum(1 for t in tasks if t["state"] == "merged")
    lines = [
        "<!-- GENERATED by scripts/campaign.py --generate. Do not edit by hand. -->",
        "# What contributors have built",
        "",
    ]
    if not merged:
        lines += [
            "**Nothing yet.** The inventory is published and the tooling works, but no "
            "campaign task has been completed and merged.",
            "",
            "That is the honest state and this page will show it until it changes. A "
            "dashboard that reports activity — tasks published, people reached — rather "
            "than merged work is how a campaign persuades itself it is succeeding while "
            "producing nothing.",
            "",
        ]
    else:
        lines += [f"**{merged} merged contributions** across the categories below.", ""]

    lines += ["| Category | Merged | Open | Total |", "|---|---:|---:|---:|"]
    for family in FAMILIES:
        rows = [t for t in tasks if t["family"] == family]
        if not rows:
            continue
        lines.append(
            f"| {family} | {sum(1 for t in rows if t['state'] == 'merged')} | "
            f"{sum(1 for t in rows if t['state'] == 'open')} | {len(rows)} |"
        )
    lines += [
        "",
        f"{s['open']} tasks are open now of {s['total']} in the inventory. The rest are "
        "held back deliberately: releasing more work than can be reviewed leaves people "
        "waiting, which costs more than a shorter list does.",
        "",
        "Reviewer load, queue age and incident details are deliberately **not** published "
        "here — those are about individuals, and aggregate output is what a reader needs.",
    ]
    return "\n".join(lines) + "\n"


def _env_of(task: dict[str, Any]) -> tuple[str, str]:
    """(filter key, human label) for what a contributor physically needs."""
    if task.get("requires"):
        return "hardware", "your own machine"
    if task["cloud_agent_ready"]:
        return "cloud", "a browser or container"
    return "local", "a local clone"


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def render_task_finder(tasks: list[dict[str, Any]]) -> str:
    """A filterable task page — self-contained, no network, no tracking.

    The static table answers "what is open"; it does not answer "which of these 297
    compatibility tasks is *mine*", which is the only question a newcomer on Fedora with
    KDE actually has. Scanning a 130-row table for it is the friction that loses people
    between arriving and starting.

    Every row is rendered into the HTML, and the script only hides and shows. With
    JavaScript disabled the page is a complete, readable list rather than an empty box —
    and there is no request to anywhere, which is the only acceptable behaviour on the
    documentation site of a tool whose entire claim is that nothing leaves your machine.
    """
    openable = sorted(
        (t for t in tasks if t["state"] == "open"),
        key=lambda t: (t["minutes"], t["family"], t["id"]),
    )
    families = sorted({t["family"] for t in openable})

    rows: list[str] = []
    for t in openable:
        env_key, env_label = _env_of(t)
        skills = ", ".join(t["skills"]) or "no coding"
        needs = ", ".join(sorted((t.get("requires") or {}).values())) or env_label
        rows.append(
            f'<tr class="yz-row" data-env="{env_key}" data-family="{t["family"]}" '
            f'data-minutes="{t["minutes"]}" data-skills="{_escape(skills.lower())}" '
            f'data-text="{_escape((t["title"] + " " + needs).lower())}">'
            f'<td><strong>{_escape(t["title"])}</strong><br>'
            f'<code>{t["id"]}</code> · {t["risk"]} · {t["minutes"]} min</td>'
            f'<td>{_escape(needs)}</td><td>{_escape(skills)}</td></tr>'
        )

    options = "".join(f'<option value="{f}">{f}</option>' for f in families)
    return f"""---
title: Find a task that fits you
description: Filter {len(openable)} open YazSes contributor tasks by what you have — a browser, a laptop, specific hardware — how much time, and whether you want to write code.
---

# Find a task that fits you

Filter by what you actually have. Nothing is assigned and you need no permission — pick one,
say so on the issue it links to, and open the pull request.
[How to make your first contribution](start.md) if you want the short version.

<div class="yz-filters" markdown="0">
  <label>What you have
    <select id="yz-env">
      <option value="">anything</option>
      <option value="cloud">just a browser</option>
      <option value="local">a laptop I can clone onto</option>
      <option value="hardware">specific hardware or an OS</option>
    </select>
  </label>
  <label>Time
    <select id="yz-time">
      <option value="">any</option>
      <option value="20">under 20 min</option>
      <option value="30">under 30 min</option>
      <option value="60">under 60 min</option>
    </select>
  </label>
  <label>Kind
    <select id="yz-family"><option value="">all</option>{options}</select>
  </label>
  <label>Search
    <input id="yz-q" type="search" placeholder="fedora, kitty, hindi…" autocomplete="off">
  </label>
</div>

<p id="yz-count"><strong>{len(openable)}</strong> tasks shown.</p>

<table class="yz-table">
<thead><tr><th>Task</th><th>You need</th><th>Skills</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>

<style>
.yz-filters {{ display: flex; flex-wrap: wrap; gap: 1rem; margin: 1rem 0; }}
.yz-filters label {{ display: flex; flex-direction: column; font-size: .75rem; font-weight: 700; }}
.yz-filters select, .yz-filters input {{ margin-top: .25rem; padding: .35rem; font-size: .8rem; }}
.yz-table td {{ vertical-align: top; }}
</style>

<script>
(function () {{
  var env = document.getElementById('yz-env'), time = document.getElementById('yz-time'),
      fam = document.getElementById('yz-family'), q = document.getElementById('yz-q'),
      count = document.getElementById('yz-count'),
      rows = Array.prototype.slice.call(document.querySelectorAll('.yz-row'));
  function apply() {{
    var e = env.value, t = parseInt(time.value || '0', 10), f = fam.value,
        s = (q.value || '').trim().toLowerCase(), shown = 0;
    rows.forEach(function (r) {{
      var ok = (!e || r.dataset.env === e)
        && (!t || parseInt(r.dataset.minutes, 10) <= t)
        && (!f || r.dataset.family === f)
        && (!s || r.dataset.text.indexOf(s) !== -1 || r.dataset.skills.indexOf(s) !== -1);
      r.style.display = ok ? '' : 'none';
      if (ok) shown++;
    }});
    count.innerHTML = '<strong>' + shown + '</strong> task' + (shown === 1 ? '' : 's')
      + ' shown.' + (shown ? '' : ' Try widening a filter — every task here is real work.');
  }}
  [env, time, fam].forEach(function (el) {{ el.addEventListener('change', apply); }});
  q.addEventListener('input', apply);
}})();
</script>
"""


#: A generated page cannot carry hand-added front matter -- it is overwritten on every
#: regeneration -- so its description belongs to the generator. Without one MkDocs falls
#: back to the site-wide description, and the page ships the same search snippet as every
#: other page that lacks it: indistinguishable both to a search engine and to a reader
#: scanning results. Only the `docs/` copies are published, so only they get it; the
#: `campaign/generated/` originals would carry an unread YAML block.
_DOCS_TASKS_DESCRIPTION = (
    "Every open YazSes contributor task, grouped by family, with the time each takes "
    "and whether it needs Python, a browser container or your own machine. Nothing is "
    "assigned; pick one and say so."
)
_DOCS_BUILT_DESCRIPTION = (
    "What contributors have actually built and merged in YazSes, counted by category. "
    "It reports merged work rather than activity, and shows zeros honestly until real "
    "work lands."
)


def _with_description(description: str, body: str) -> str:
    """Prepend a MkDocs front-matter block declaring *description*.

    Double quotes are rejected rather than escaped: MkDocs writes the value straight
    into `<meta name=description content="...">` without escaping, so one would close
    the attribute early and leak the rest of the sentence out as junk attributes --
    with a green build (see tests/test_docs_frontmatter.py).
    """
    assert '"' not in description, "a double quote would truncate the rendered meta tag"
    return f'---\ndescription: "{description}"\n---\n\n{body}'


def generate(tasks: list[dict[str, Any]]) -> dict[Path, str]:
    """Every generated artifact, as path -> content. Written only by --generate."""
    return {
        SCHEMA_JSON: json.dumps(json_schema(), indent=2) + "\n",
        OPEN_TASKS_MD: render_open_tasks(tasks),
        DASHBOARD_MD: render_dashboard(tasks),
        STATS_JSON: json.dumps(stats(tasks), indent=2) + "\n",
        DOCS_TASKS_MD: _with_description(
            _DOCS_TASKS_DESCRIPTION, render_open_tasks(tasks)
        ),
        DOCS_BUILT_MD: _with_description(
            _DOCS_BUILT_DESCRIPTION, render_dashboard(tasks)
        ),
        DOCS_FINDER_MD: render_task_finder(tasks),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate the inventory and generated files")
    ap.add_argument("--generate", action="store_true", help="rewrite the generated files")
    ap.add_argument("--stats", action="store_true", help="print a summary")
    args = ap.parse_args(argv)
    if not (args.check or args.generate or args.stats):
        ap.print_help()
        return 2

    tasks = load_tasks()
    errors = validate_inventory(tasks)
    if errors:
        print(f"✗ {len(errors)} problem(s) in {TASKS_JSON.relative_to(ROOT)}:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    wanted = generate(tasks)
    if args.generate:
        for path, content in wanted.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    elif args.check:
        stale = [
            p.relative_to(ROOT)
            for p, c in wanted.items()
            if not p.exists() or p.read_text(encoding="utf-8") != c
        ]
        if stale:
            print(
                f"✗ generated files are stale: {stale}\n"
                "  run: uv run python scripts/campaign.py --generate",
                file=sys.stderr,
            )
            return 1
        print(f"✓ {len(tasks)} tasks valid, generated files in sync")

    if args.stats:
        print(json.dumps(stats(tasks), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
