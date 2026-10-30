"""The Hugging Face publish workflow can only publish what the manifest approves, only
from main, only on purpose.

These are the properties that make a manual `workflow_dispatch` that holds an OIDC
token safe to leave in the repository (CI_POLICY.md sections 2, 3, 7, 11). They are read
from the workflow file and cross-checked against `huggingface/manifest.json`, so adding a
destination to one without the other fails here.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _load(name: str):
    """Load scripts/<name>.py by path, as tests/test_ci_telemetry.py does: the FreeBSD
    leg and the test-dependency guard treat a `sys.path` name import as a missing package."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module

pf = _load("hf_preflight")

WORKFLOW = ROOT / ".github" / "workflows" / "huggingface-publish.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
DOC = yaml.safe_load(TEXT)
# YAML 1.1 reads the key `on` as the boolean True.
TRIGGERS = DOC.get(True, DOC.get("on"))
JOBS = DOC["jobs"]
MANIFEST = json.loads(pf.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
DESTS = MANIFEST["destinations"]

_USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+?)\s*(?:#\s*(?P<comment>.+?))?\s*$", re.M)
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _publish_steps() -> list[dict]:
    return JOBS["publish"]["steps"]


def _step(name: str) -> dict:
    return next(s for s in _publish_steps() if s.get("name") == name)


# --- triggers --------------------------------------------------------------------


def test_the_only_trigger_is_workflow_dispatch() -> None:
    assert set(TRIGGERS) == {"workflow_dispatch"}
    for forbidden in ("push", "pull_request", "pull_request_target", "schedule", "workflow_run",
                      "release", "issue_comment", "repository_dispatch", "workflow_call"):
        assert forbidden not in TRIGGERS


def test_dry_run_defaults_to_true_and_is_required() -> None:
    dry = TRIGGERS["workflow_dispatch"]["inputs"]["dry_run"]
    assert dry["type"] == "boolean" and dry["default"] is True and dry["required"] is True


def test_the_target_choices_are_exactly_the_manifest_destinations_plus_all_approved() -> None:
    target = TRIGGERS["workflow_dispatch"]["inputs"]["target"]
    assert target["type"] == "choice"
    assert sorted(target["options"]) == sorted([*DESTS, "all-approved"])
    assert target["default"] in DESTS, "the default must be one named destination, never a sweep"


# --- permissions, concurrency, timeouts ------------------------------------------------


def test_default_permissions_are_read_only() -> None:
    assert DOC["permissions"] == {"contents": "read"}


def test_id_token_write_exists_only_in_the_publish_job() -> None:
    assert "id-token" not in json.dumps(DOC["permissions"])
    assert "id-token" not in json.dumps(JOBS["validate"])
    assert JOBS["publish"]["permissions"] == {"contents": "read", "id-token": "write"}
    keys = [line for line in TEXT.splitlines() if re.match(r"^\s*id-token:\s*write\b", line)]
    assert len(keys) == 1, keys


def test_validate_has_no_secrets_environment_or_write_permission() -> None:
    validate = JOBS["validate"]
    assert "environment" not in validate
    assert "permissions" not in validate, "it inherits the read-only default"
    assert "if" not in validate
    assert "secrets" not in json.dumps(validate)


def test_the_job_that_can_request_the_oidc_token_pins_uv_exactly() -> None:
    installs = [s for s in _publish_steps() if str(s.get("uses", "")).endswith("setup-uv-python")]
    assert installs, "the publish job must install its dependencies through the composite action"
    for step in installs:
        version = str(step.get("with", {}).get("uv-version", ""))
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"uv is not pinned to an exact version: {version!r}"


def test_publishing_is_serialised_and_never_cancelled() -> None:
    conc = DOC["concurrency"]
    assert conc["cancel-in-progress"] is False
    assert "pull_request" not in conc["group"]
    assert "github.ref" not in conc["group"], "one group for every ref: two publishes never overlap"


@pytest.mark.parametrize("job", sorted(JOBS))
def test_every_job_declares_a_timeout(job) -> None:
    timeout = JOBS[job].get("timeout-minutes")
    assert isinstance(timeout, int) and 0 < timeout <= 60


# --- the publish gate ------------------------------------------------------------------


def test_publish_needs_validate_and_is_gated_on_main_dry_run_and_the_repository() -> None:
    publish = JOBS["publish"]
    assert publish["needs"] == "validate"
    condition = publish["if"]
    assert "inputs.dry_run == false" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "github.repository == 'MSKazemi/yazses'" in condition
    assert " || " not in condition, "the gate must be a pure conjunction"


def test_publish_uses_the_approval_environment_named_in_the_manifest() -> None:
    env = JOBS["publish"]["environment"]
    name = env["name"] if isinstance(env, dict) else env
    assert name == MANIFEST["oidc_publisher"]["environment"] == "huggingface-publish"


def test_the_oidc_publisher_claims_match_this_workflow() -> None:
    tp = MANIFEST["oidc_publisher"]
    assert tp["workflow"] == WORKFLOW.name
    assert tp["branch"] == "main" and tp["provider"] == "github-actions"
    assert tp["repository"] == "MSKazemi/yazses"


def test_publish_revalidates_with_require_approved_before_any_upload() -> None:
    steps = _publish_steps()
    stage = next(i for i, s in enumerate(steps) if s.get("id") == "stage")
    first_upload = next(i for i, s in enumerate(steps) if "hf upload" in s.get("run", ""))
    assert stage < first_upload
    run = steps[stage]["run"]
    assert "--require-approved" in run and "--stage-dir" in run and "--github-output" in run
    assert "hf_preflight.py" in run


def test_validate_runs_the_preflight_and_requires_approval_only_for_a_real_publish() -> None:
    runs = "\n".join(s.get("run", "") for s in JOBS["validate"]["steps"])
    assert "hf_preflight.py" in runs and "--print-plan" in runs
    assert '"$DRY_RUN" != "true"' in runs and "--require-approved" in runs
    assert "hf_collection.py --offline" in runs, "validation may only use the offline collection plan"
    assert "--apply" not in runs


# --- one upload step per manifest destination, with its own identity ----------------------


@pytest.mark.parametrize("name", sorted(DESTS))
def test_each_destination_has_exactly_one_scoped_upload_step(name) -> None:
    dest = DESTS[name]
    steps = [s for s in _publish_steps() if f"'{name}'" in str(s.get("if", ""))]
    assert len(steps) == 1, f"{name}: expected one upload step, found {len(steps)}"
    step = steps[0]
    assert step["env"]["HF_OIDC_RESOURCE"] == pf.oidc_resource(dest)
    assert step["env"]["DEST"] == name
    run = step["run"]
    assert f'hf upload "{dest["repo_id"]}"' in run
    assert f"--repo-type {dest['repo_type']}" in run
    assert f"https://huggingface.co/{'spaces' if dest['repo_type'] == 'space' else 'datasets'}/{dest['repo_id']}" in run
    assert '"$RUNNER_TEMP/hf-stage/$DEST" .' in run, "uploads the staged allowlist, never the source tree"
    assert "contains(fromJSON(steps.stage.outputs.selected)" in step["if"]


def test_every_destination_has_a_distinct_publisher_and_oidc_resource() -> None:
    resources = [pf.oidc_resource(d) for d in DESTS.values()]
    assert len(set(resources)) == len(resources)
    publishers = [d["publisher"] for d in DESTS.values()]
    assert len(set(publishers)) == len(publishers)


def test_the_upload_steps_are_the_only_steps_with_hf_oidc_resource() -> None:
    carrying = [s["name"] for s in _publish_steps() if "HF_OIDC_RESOURCE" in s.get("env", {})]
    assert sorted(carrying) == sorted(f"Publish {n}" for n in DESTS)
    assert "HF_OIDC_RESOURCE" not in json.dumps(DOC["permissions"])
    assert "HF_OIDC_RESOURCE" not in json.dumps(JOBS["validate"])


# --- nothing destructive, nothing secret ----------------------------------------------------


def test_no_delete_flag_anywhere() -> None:
    code = "\n".join(line for line in TEXT.splitlines() if not line.lstrip().startswith("#"))
    assert "--delete" not in code
    assert "--create-pr" not in code and "--private" not in code
    assert all(d["delete_remote_files"] is False for d in DESTS.values())


def test_no_secret_or_static_token_is_used() -> None:
    code = "\n".join(line for line in TEXT.splitlines() if not line.lstrip().startswith("#"))
    for needle in ("secrets.", "HF_TOKEN", "--token", "HUGGING_FACE_HUB_TOKEN", "hf auth login",
                   "huggingface-cli login", "ACTIONS_ID_TOKEN"):
        assert needle not in code, needle


def test_the_exchanged_token_is_never_printed() -> None:
    for step in _publish_steps():
        run = step.get("run", "")
        for match in re.finditer(r"hf auth token[^\n]*", run):
            assert ">/dev/null" in match.group(0), f"`hf auth token` must discard stdout: {match.group(0)}"
        assert "set -x" not in run and "xtrace" not in run
        assert not re.search(r"^\s*(env|printenv|export -p)\b", run, re.M)
        assert "echo \"$HF_" not in run and "echo $HF_" not in run
    assert "set -x" not in TEXT


def test_no_expression_interpolation_into_shell() -> None:
    """Inputs and contexts reach scripts through env, never inside `run:` (CI_POLICY 7.4)."""
    for job in JOBS.values():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), step.get("name")


# --- repository-wide conventions -------------------------------------------------------------


def test_every_action_is_pinned_to_a_sha_with_a_version_comment_or_is_local() -> None:
    refs = [(m.group("ref").strip("'\""), m.group("comment")) for m in _USES.finditer(TEXT)]
    assert refs
    for ref, comment in refs:
        if ref.startswith("./"):
            assert (ROOT / ref[2:]).is_dir(), ref
            continue
        assert "@" in ref and _SHA.match(ref.split("@", 1)[1]), f"{ref} must be pinned to a commit"
        assert comment, f"{ref} needs a version comment"


def test_checkouts_do_not_persist_credentials() -> None:
    for job in JOBS.values():
        for step in job["steps"]:
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False


def test_python_setup_uses_the_repository_composite_with_a_pinned_interpreter() -> None:
    for job in JOBS.values():
        setups = [s for s in job["steps"] if s.get("uses") == "./.github/actions/setup-uv-python"]
        assert len(setups) == 1
        assert setups[0]["with"]["python-version"] == "3.12"
        assert "--frozen" in setups[0]["with"]["sync-args"]


def test_the_workflow_is_the_only_place_that_can_publish() -> None:
    """No other workflow, script or test invokes `hf upload` or an upload API."""
    offenders = []
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        if path.name != WORKFLOW.name and re.search(r"\bhf upload\b|HF_OIDC_RESOURCE", path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    for path in (ROOT / "scripts").glob("hf_*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in ("upload_file(", "upload_folder(", "create_commit(", "hf upload"):
            if needle in text:
                offenders.append(f"{path.name}:{needle}")
    assert offenders == []
