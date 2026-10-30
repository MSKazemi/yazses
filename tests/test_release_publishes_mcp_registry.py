"""`release.yml`'s `publish-mcp-registry` job: off until the owner turns it on (#639).

ADR-032 §2 says publishing to the MCP registry "joins the release workflow only after
the owner approves it, under `.github/CI_POLICY.md`". So the job exists, and is
skipped unless the repository variable `MCP_REGISTRY_PUBLISH` is `true`: an unset
variable reads as the empty string, so a release with no decision publishes nothing.

What the job must get right, each of which would otherwise surface only on a release:

* it never runs off a tag or without the variable, and gains no write permission;
* it publishes the file rendered from the **tagged** checkout, refusing a tag that is
  not `v<pyproject version>` and a README without the ownership marker;
* it waits for PyPI to serve that version with the marker — the registry fetches the
  same URL and rejects a publish that comes too early;
* the `mcp-publisher` it runs is a pinned release, checked against a pinned SHA-256;
* it logs in with GitHub OIDC (no stored secret) before it publishes.

The render and wait steps are run verbatim here against a fabricated checkout and a
`curl` shim, so nothing contacts PyPI or the registry. The publish itself is the check
these tests cannot make.
"""

from __future__ import annotations

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
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
JOB = "publish-mcp-registry"
SERVER_JSON = "mcp-registry/server.json"
_PINNED = re.compile(r"@[0-9a-f]{40}$")

_needs_the_workflow_runner = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="the steps under test are Linux `run:` blocks (see runs-on in the workflow)",
)


def _job() -> dict:
    return yaml.safe_load(RELEASE.read_text(encoding="utf-8"))["jobs"][JOB]


def _steps() -> list[dict]:
    return _job()["steps"]


def _index(predicate) -> int:
    hits = [i for i, s in enumerate(_steps()) if predicate(s)]
    assert len(hits) == 1, f"expected exactly one matching step, found {len(hits)}"
    return hits[0]


def _run_containing(text: str) -> int:
    return _index(lambda s: text in str(s.get("run") or ""))


def _version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


# --- the gate --------------------------------------------------------------------


def test_the_job_is_off_unless_the_owner_turns_it_on() -> None:
    """Both conditions, joined by `&&`: a tag, and the owner's variable set to `true`."""
    condition = _job()["if"]
    assert condition == "github.ref_type == 'tag' && vars.MCP_REGISTRY_PUBLISH == 'true'"


def test_the_job_runs_after_pypi_has_the_release() -> None:
    assert _job()["needs"] == "publish-pypi"


def test_the_job_has_no_write_permission_and_no_secret() -> None:
    """OIDC is the whole credential (CI_POLICY §7 rule 7)."""
    job = _job()
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert "secrets." not in RELEASE.read_text(encoding="utf-8").split(f"  {JOB}:")[1].split(
        "\n  build-deb:"
    )[0]


def test_the_job_has_an_environment_the_owner_can_protect() -> None:
    assert _job()["environment"] == "mcp-registry"


# --- the steps, in order -----------------------------------------------------------


def test_every_action_is_pinned_to_a_commit() -> None:
    for step in _steps():
        if "uses" in step:
            assert _PINNED.search(step["uses"]), step["uses"]


def test_the_checkout_is_the_tag() -> None:
    checkout = _index(lambda s: str(s.get("uses") or "").startswith("actions/checkout@"))
    assert "ref" not in (_steps()[checkout].get("with") or {})
    assert checkout == 0


def test_the_steps_render_then_wait_then_install_then_publish() -> None:
    render = _run_containing("--check-readme")
    wait = _run_containing("--check-pypi-json")
    install = _run_containing("sha256sum -c")
    publish = _run_containing("mcp-publisher publish")
    assert render < wait < install < publish


def test_the_render_step_refuses_a_wrong_tag_and_a_missing_marker() -> None:
    run = _steps()[_run_containing("--check-readme")]["run"]
    assert "set -euo pipefail" in run
    assert "python3 scripts/render-mcp-server-json.py --out-dir mcp-registry" in run
    assert '--expect-tag "$GITHUB_REF_NAME"' in run


def test_the_wait_polls_the_url_the_registry_reads() -> None:
    """internal/validators/registries/pypi.go fetches `<base>/pypi/<name>/<version>/json`."""
    run = _steps()[_run_containing("--check-pypi-json")]["run"]
    assert 'url="https://pypi.org/pypi/yazses/${GITHUB_REF_NAME#v}/json"' in run
    assert '--expect-tag "$GITHUB_REF_NAME"' in run


def test_mcp_publisher_is_pinned_and_content_checked() -> None:
    env = _job()["env"]
    assert re.fullmatch(r"v\d+\.\d+\.\d+", env["MCP_PUBLISHER_VERSION"])
    assert re.fullmatch(r"[0-9a-f]{64}", env["MCP_PUBLISHER_SHA256"])
    run = _steps()[_run_containing("sha256sum -c")]["run"]
    assert "releases/download/${MCP_PUBLISHER_VERSION}/" in run
    assert "latest" not in run
    assert run.index("sha256sum -c") < run.index("tar xzf")


def test_it_logs_in_with_oidc_and_publishes_the_rendered_file() -> None:
    run = _steps()[_run_containing("mcp-publisher publish")]["run"]
    assert "set -euo pipefail" in run
    assert run.index("./mcp-publisher login github-oidc") < run.index("./mcp-publisher publish")
    assert f"./mcp-publisher publish {SERVER_JSON}" in run


def test_no_other_job_publishes_to_the_registry() -> None:
    jobs = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))["jobs"]
    others = [n for n, j in jobs.items() if n != JOB and "mcp-publisher" in json.dumps(j)]
    assert others == []


# --- the render and wait steps, run verbatim -------------------------------------


def _fake_checkout(tmp_path: Path, version: str, readme: str | None = None) -> Path:
    root = tmp_path / "checkout"
    for rel in (
        "scripts/render-mcp-server-json.py",
        "scripts/build-mcpb.py",
        "packaging/mcp-registry/server.template.json",
        "README.md",
    ):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, root / rel)
    if readme is not None:
        (root / "README.md").write_text(readme, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "yazses"\nversion = "{version}"\n', encoding="utf-8"
    )
    return root


def _shims(tmp_path: Path, pypi_answers: list[dict | None]) -> Path:
    """`python3` -> this interpreter; `sleep` -> no-op; `curl` -> the next fabricated
    PyPI answer (None = HTTP failure), so the wait loop runs offline and at once."""
    shim = tmp_path / "bin"
    shim.mkdir(exist_ok=True)
    (shim / "python3").symlink_to(sys.executable)
    (shim / "sleep").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    answers = tmp_path / "answers"
    answers.mkdir(exist_ok=True)
    for i, answer in enumerate(pypi_answers):
        if answer is not None:
            (answers / str(i)).write_text(json.dumps(answer), encoding="utf-8")
    (shim / "curl").write_text(
        "#!/bin/bash\n"
        f'calls="{tmp_path}/curl-calls"\n'
        'n=$(( $(cat "$calls" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$calls"\n'
        'out=""; while [ $# -gt 0 ]; do\n'
        '  if [ "$1" = "-o" ]; then out="$2"; shift; fi\n'
        '  case "$1" in https://*) echo "$1" >> "' + str(tmp_path) + '/curl-urls";; esac\n'
        "  shift\n"
        "done\n"
        f'src="{answers}/$n"\n'
        '[ -f "$src" ] || exit 22\n'
        'cp "$src" "$out"\n',
        encoding="utf-8",
    )
    for name in ("sleep", "curl"):
        (shim / name).chmod(0o755)
    return shim


def _run_step(text: str, root: Path, tag: str, shim: Path) -> subprocess.CompletedProcess:
    run = _steps()[_run_containing(text)]["run"]
    env = {
        "PATH": f"{shim}{os.pathsep}{os.environ.get('PATH', '')}",
        "GITHUB_REF_NAME": tag,
        "HOME": str(shim.parent),
    }
    return subprocess.run(
        ["bash", "-c", run], cwd=root, env=env, capture_output=True, text=True, timeout=60,
    )


def _pypi(version: str, description: str) -> dict:
    return {"info": {"name": "yazses", "version": version, "description": description}}


@_needs_the_workflow_runner
def test_the_render_step_writes_the_file_the_publish_step_reads(tmp_path: Path) -> None:
    root = _fake_checkout(tmp_path, "97.5.3")
    proc = _run_step("--check-readme", root, "v97.5.3", _shims(tmp_path, []))
    assert proc.returncode == 0, proc.stderr
    server = json.loads((root / SERVER_JSON).read_text(encoding="utf-8"))
    assert server["version"] == server["packages"][0]["version"] == "97.5.3"


@_needs_the_workflow_runner
@pytest.mark.parametrize(
    ("tag", "readme", "why"),
    [
        ("v97.5.4", None, "does not match"),
        ("v97.5.3", "# YazSes\n\nNo marker here.\n", "ownership marker"),
    ],
)
def test_the_render_step_fails_and_writes_nothing(
    tmp_path: Path, tag: str, readme: str | None, why: str
) -> None:
    root = _fake_checkout(tmp_path, "97.5.3", readme)
    proc = _run_step("--check-readme", root, tag, _shims(tmp_path, []))
    assert proc.returncode != 0
    assert why in proc.stderr
    assert not (root / SERVER_JSON).exists()


@_needs_the_workflow_runner
def test_the_wait_step_retries_until_pypi_shows_the_marker(tmp_path: Path) -> None:
    """Not yet on PyPI, then on PyPI without the marker (a README glued to a full stop),
    then right: the step keeps polling the registry's URL and succeeds on the third."""
    root = _fake_checkout(tmp_path, "97.5.3")
    good = _pypi("97.5.3", "# YazSes\n\n<!-- mcp-name: io.github.MSKazemi/yazses -->\n")
    glued = _pypi("97.5.3", "see mcp-name: io.github.MSKazemi/yazses.")
    shim = _shims(tmp_path, [None, None, glued, good])  # call n answers with item n
    proc = _run_step("--check-pypi-json", root, "v97.5.3", shim)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "curl-calls").read_text(encoding="utf-8").strip() == "3"
    urls = set((tmp_path / "curl-urls").read_text(encoding="utf-8").split())
    assert urls == {"https://pypi.org/pypi/yazses/97.5.3/json"}
