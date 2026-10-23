"""Every tagged release builds, attests, attaches and checksums the `.mcpb` (ADR-032 §1).

`scripts/build-mcpb.py` existed for a release before anything ran it, so the guide had
to tell users to build the bundle from a checkout. ADR-032 §1 says the bundle "is built
in CI from a template, attached to each GitHub release beside the other assets, and
covered by the release checksum file". Each half of that lives in a different file, and
a gap in any one of them is silent: the release still goes green.

* `release.yml`, job `release-linux`: builds it from the **tagged** checkout, refusing a
  tag that is not `v<pyproject version>`, attests it, attaches the bundle *and* its own
  provenance file.
* `checksums.yml`: downloads it, hashes it, and proves `SHA256SUMS.txt` is newer.
* `scripts/verify-release-assets.py` and `scripts/verify-provenance.py`: the audits
  `release-complete.yml` and a maintainer run against a published release.

The bundle's file name is DERIVED by building it with the real script, never written
here, so a renamed bundle fails this file instead of leaving the globs behind. Nothing
here cuts a tag; the first real release is the check these tests cannot make.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML ships with the docs group")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
RELEASE = WORKFLOWS / "release.yml"
CHECKSUMS = WORKFLOWS / "checksums.yml"
SCRIPT = ROOT / "scripts" / "build-mcpb.py"

ATTEST_ACTION = "actions/attest-build-provenance"
RELEASE_ACTION = "softprops/action-gh-release"
_PINNED = re.compile(r"@[0-9a-f]{40}$")

# The build step is a Linux `run:` block on ubuntu-latest; executing it verbatim needs
# that shell. Same condition, and the same reasoning, as
# tests/test_checksums_workflow_waits_for_builds.py.
_needs_the_workflow_runner = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="the step under test is a Linux `run:` block (see runs-on in the workflow)",
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


mcpb = _load("build_mcpb_for_release", SCRIPT)


def _version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


@pytest.fixture(scope="module")
def bundle_name(tmp_path_factory) -> str:
    """The name the real script gives the bundle for the current version."""
    name = mcpb.build(tmp_path_factory.mktemp("mcpb-name")).name
    assert name.endswith(".mcpb"), name
    return name


def _job(path: Path, job: str) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc["jobs"][job]


def _release_steps() -> list[dict]:
    return _job(RELEASE, "release-linux")["steps"]


def _index(steps: list[dict], predicate) -> int:
    hits = [i for i, s in enumerate(steps) if predicate(s)]
    assert len(hits) == 1, f"expected exactly one matching step, found {len(hits)}"
    return hits[0]


def _build_index(steps: list[dict]) -> int:
    return _index(steps, lambda s: "scripts/build-mcpb.py" in str(s.get("run") or ""))


def _mcpb_attest_index(steps: list[dict]) -> int:
    return _index(
        steps,
        lambda s: ATTEST_ACTION in str(s.get("uses") or "")
        and ".mcpb" in str((s.get("with") or {}).get("subject-path") or ""),
    )


def _release_index(steps: list[dict]) -> int:
    return _index(steps, lambda s: RELEASE_ACTION in str(s.get("uses") or ""))


def _release_globs(steps: list[dict]) -> list[str]:
    files = (steps[_release_index(steps)].get("with") or {}).get("files") or ""
    return [line.strip() for line in str(files).splitlines() if line.strip()]


# --- release.yml: built from the tag ----------------------------------------------


def test_the_release_job_builds_the_bundle_once() -> None:
    steps = _release_steps()
    run = steps[_build_index(steps)]["run"]
    assert "python3 scripts/build-mcpb.py" in run
    assert "set -euo pipefail" in run, "a failed build must stop the job before the upload"


def test_the_bundle_is_built_only_on_a_tag() -> None:
    """`release.yml` also runs on workflow_dispatch from main; a bundle built there
    would come from whatever main holds, not from a release."""
    assert _job(RELEASE, "release-linux").get("if") == "github.ref_type == 'tag'"


def test_the_build_refuses_a_tag_that_is_not_the_pyproject_version() -> None:
    steps = _release_steps()
    run = steps[_build_index(steps)]["run"]
    assert '--expect-tag "$GITHUB_REF_NAME"' in run, (
        "the release build must pass the tag, so a tag on an unbumped commit cannot ship "
        "a bundle whose manifest names the previous release"
    )


def test_the_build_runs_from_the_checked_out_tag_with_nothing_installed() -> None:
    """The job's checkout (default ref = the pushed tag) precedes the build, and no
    step in this job installs Python packages: the script is standard library only."""
    steps = _release_steps()
    checkout = _index(steps, lambda s: str(s.get("uses") or "").startswith("actions/checkout@"))
    assert checkout < _build_index(steps)
    assert "ref" not in (steps[checkout].get("with") or {}), (
        "a pinned checkout ref would build the bundle from something other than the tag"
    )
    for step in steps:
        run = str(step.get("run") or "")
        assert "pip install" not in run and "uv " not in run, step.get("name")


def test_the_bundle_is_built_before_it_is_attested_and_released() -> None:
    steps = _release_steps()
    assert _build_index(steps) < _mcpb_attest_index(steps) < _release_index(steps)


# --- release.yml: attested and attached -------------------------------------------


def test_the_bundle_is_attested_by_a_pinned_addressable_step(bundle_name: str) -> None:
    steps = _release_steps()
    step = steps[_mcpb_attest_index(steps)]
    assert _PINNED.search(step["uses"]), step["uses"]
    assert step.get("id"), "the bundle-path output needs a step id"
    subject = str(step["with"]["subject-path"]).strip().strip("\"'")
    assert fnmatch.fnmatchcase(bundle_name, subject), (bundle_name, subject)


def test_the_mcpb_attest_step_uses_the_same_pin_as_the_deb_one() -> None:
    """One action, one reviewed SHA: a second pin would be a second thing to bump."""
    uses = {
        s["uses"] for s in _release_steps() if ATTEST_ACTION in str(s.get("uses") or "")
    }
    assert len(uses) == 1, uses


def test_the_bundle_and_its_provenance_file_are_attached(bundle_name: str) -> None:
    steps = _release_steps()
    globs = _release_globs(steps)
    assert any(fnmatch.fnmatchcase(bundle_name, g) for g in globs), (bundle_name, globs)

    attest_id = steps[_mcpb_attest_index(steps)]["id"]
    copies = [
        s for s in steps
        if f"steps.{attest_id}.outputs.bundle-path" in json.dumps(s.get("env") or {})
        or f"steps.{attest_id}.outputs.bundle-path" in str(s.get("run") or "")
    ]
    assert len(copies) == 1, "the .mcpb attestation bundle is never copied out"
    m = re.search(r'"(yazses-\$\{GITHUB_REF_NAME#v\}-[a-z]+\.intoto\.jsonl)"', copies[0]["run"])
    assert m, copies[0]["run"]
    provenance = m.group(1).replace("${GITHUB_REF_NAME#v}", _version())
    assert provenance.endswith(".intoto.jsonl")
    assert provenance != f"yazses-{_version()}-deb.intoto.jsonl", (
        "the .mcpb provenance must not overwrite the .deb one"
    )
    assert any(fnmatch.fnmatchcase(provenance, g) for g in globs), (provenance, globs)
    assert _index(steps, lambda s: s is copies[0]) < _release_index(steps)


def test_the_release_job_gained_no_permission() -> None:
    """Building and attesting the bundle needs exactly what the .deb already needed."""
    assert _job(RELEASE, "release-linux")["permissions"] == {
        "contents": "write",
        "id-token": "write",
        "attestations": "write",
    }


def test_verify_provenance_now_requires_an_attestation_for_the_bundle(bundle_name: str) -> None:
    mod = _load("verify_provenance_for_mcpb", ROOT / "scripts" / "verify-provenance.py")
    assert Path(bundle_name).suffix in mod.attested_suffixes()


# --- the build step itself, run verbatim ------------------------------------------


def _fake_checkout(tmp_path: Path, version: str) -> Path:
    """The files the build reads, laid out as the release job's checkout has them."""
    root = tmp_path / "checkout"
    for rel in ("scripts/build-mcpb.py", mcpb.TEMPLATE_REL, *mcpb.EXTRA_FILES.values()):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, root / rel)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "yazses"\nversion = "{version}"\n', encoding="utf-8"
    )
    return root


def _run_build_step(root: Path, tag: str, tmp_path: Path) -> subprocess.CompletedProcess:
    steps = _release_steps()
    run = steps[_build_index(steps)]["run"]
    shim = tmp_path / "bin"
    shim.mkdir(exist_ok=True)
    (shim / "python3").symlink_to(sys.executable)
    env = {
        "PATH": f"{shim}{os.pathsep}{os.environ.get('PATH', '')}",
        "GITHUB_REF_NAME": tag,
        "HOME": str(tmp_path),
    }
    return subprocess.run(
        ["bash", "-c", run], cwd=root, env=env, capture_output=True, text=True, timeout=60,
    )


@_needs_the_workflow_runner
def test_the_step_builds_the_bundle_named_for_the_tag(tmp_path: Path) -> None:
    root = _fake_checkout(tmp_path, "97.5.3")
    proc = _run_build_step(root, "v97.5.3", tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert (root / "yazses-97.5.3.mcpb").is_file()


@_needs_the_workflow_runner
def test_the_step_fails_and_writes_nothing_when_the_tag_is_not_the_version(
    tmp_path: Path,
) -> None:
    root = _fake_checkout(tmp_path, "97.5.3")
    proc = _run_build_step(root, "v97.5.4", tmp_path)
    assert proc.returncode != 0
    assert "does not match" in proc.stderr
    assert not list(root.glob("*.mcpb")), "a refused build must leave nothing to attach"


# --- checksums.yml and the audits ---------------------------------------------------


def _checksums_step(prefix: str) -> str:
    steps = _job(CHECKSUMS, "checksums")["steps"]
    hits = [s for s in steps if s.get("name", "").startswith(prefix)]
    assert len(hits) == 1
    return hits[0]["run"]


def test_checksums_downloads_the_bundle(bundle_name: str) -> None:
    run = _checksums_step("Download assets and generate")
    line = next(ln for ln in run.splitlines() if ln.strip().startswith("for pat in"))
    patterns = re.findall(r"'([^']+)'", line)
    assert any(fnmatch.fnmatchcase(bundle_name, p) for p in patterns), (bundle_name, patterns)


def test_checksums_hashes_the_bundle(bundle_name: str) -> None:
    run = _checksums_step("Download assets and generate")
    line = next(ln for ln in run.splitlines() if ln.strip().startswith("files=("))
    globs = line.split("(", 1)[1].rsplit(")", 1)[0].split()
    assert any(fnmatch.fnmatchcase(bundle_name, g) for g in globs), (bundle_name, globs)
    assert not any(fnmatch.fnmatchcase("SHA256SUMS.txt", g) for g in globs)


def test_checksums_proves_the_bundle_predates_the_sums_file(bundle_name: str) -> None:
    run = _checksums_step("Prove SHA256SUMS.txt describes")
    m = re.search(r'test\("((?:[^"\\]|\\.)*)"\)', run)
    assert m, "the prove step no longer selects artifacts with jq test(...)"
    regex = json.loads(f'"{m.group(1)}"')
    assert re.search(regex, bundle_name), (bundle_name, regex)
    assert not re.search(regex, "SHA256SUMS.txt")


def test_verify_release_assets_checks_the_bundle(bundle_name: str) -> None:
    mod = _load("verify_release_assets_for_mcpb", ROOT / "scripts" / "verify-release-assets.py")
    assert bundle_name.endswith(mod.ARTIFACT_SUFFIXES), (bundle_name, mod.ARTIFACT_SUFFIXES)
