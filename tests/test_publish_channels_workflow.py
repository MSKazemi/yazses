"""Publishing jobs must carry the credentials the scripts they run need.

`refresh-package-manifests.py` shells out to `gh release view` to read the
published assets. A job that runs it without GH_TOKEN dies with "set the
GH_TOKEN environment variable" — and because the AUR job also holds an SSH
secret, that read for a long time as a missing AUR credential when the
credential was fine. The AUR push had never once succeeded.

The failure is invisible until a tag is cut, so check the wiring here instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML ships with the docs group")

_WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github" / "workflows" / "publish-channels.yml"
)

_NEEDS_GH = "refresh-package-manifests.py"


def _jobs() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _env_of(job: dict, step: dict) -> dict:
    merged = dict(job.get("env") or {})
    merged.update(step.get("env") or {})
    return merged


def _steps_running_the_refresher():
    for job_name, job in _jobs().items():
        for step in job.get("steps") or []:
            if _NEEDS_GH in (step.get("run") or ""):
                yield job_name, step, _env_of(job, step)


def test_some_job_actually_runs_the_refresher():
    """Guards the guard — if the script is renamed, the check below would pass
    by finding nothing."""
    assert list(_steps_running_the_refresher()), (
        f"no step runs {_NEEDS_GH}; update this test if it moved"
    )


@pytest.mark.parametrize("var", ["GH_TOKEN", "GH_REPO"])
def test_every_refresher_step_has_the_gh_credentials(var):
    missing = [
        f"{job}/{step.get('name', '<unnamed>')}"
        for job, step, env in _steps_running_the_refresher()
        if var not in env
    ]
    assert not missing, (
        f"{missing} run {_NEEDS_GH} without {var}; `gh release view` inside it "
        f"will fail and the channel will silently never publish"
    )
