"""On Linux the voiceprint stack installs CPU torch, not CUDA torch.

Gap 7 of `design/research/2026-10-21-pay-for-what-you-enable.md`: `speechbrain>=1.1`,
the one line in the `voiceprint` extra, resolves on Linux to torch **plus the NVIDIA
CUDA stack** -- measured on 2026-10-21 against `uv.lock`: 15 `nvidia-*` distributions,
4.22 GB of wheels, under a 527 MB torch wheel, for a CPU-only offline dictation tool.
PyPI's macOS wheels are already CPU-only, and PyPI's Windows wheel carries no CUDA
dependencies either; Linux is the one platform where PyPI's torch is the CUDA build.

The PyTorch project publishes CPU-only wheels on its own index,
`https://download.pytorch.org/whl/cpu`. Resolved there, the same `speechbrain>=1.1`
closure measured 39 distributions instead of 58, zero `nvidia-*`, and every non-torch
package at the identical version (`uv pip install --dry-run`, 2026-10-21).

Two places have to agree for a user to actually get that:

* `pyproject.toml` / `uv.lock` -- what `uv sync --extra voiceprint`, the checkout and
  the release builds resolve. An **explicit** index pinned to `torch`/`torchaudio` under
  a Linux marker, so no other package can resolve from the mirror (it hosts stale copies
  of numpy, setuptools and requests) and macOS stays on PyPI.
* `system/deps.py` -- what `yazses features enable cocktail` runs on an installed copy,
  which never sees the lock. The install argv carries the index only when a package that
  pulls torch is being installed, and only on Linux.

For uv the flag pair is `--index URL --index-strategy unsafe-best-match`, not the bare
index: uv's default `first-index` strategy takes **every** package the mirror hosts from
the mirror, and the mirror's copies are old -- the dry run resolved setuptools 78.1.0
(below the patched 83.0.0 that `test_dependency_advisories.py` holds the lock to),
requests 2.28.1 and urllib3 1.26.13. `unsafe-best-match` is pip's semantics: best
version across all indexes, so PyPI wins everything the mirror is behind on and the
`+cpu` local version wins torch. Both indexes are first-party hosts, which is the only
reason the "unsafe" is acceptable here.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

from yazses.system import deps

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
LOCK = (ROOT / "uv.lock").read_text(encoding="utf-8")

URL = "https://download.pytorch.org/whl/cpu"
LINUX = {"sys_platform": "linux"}
MACOS = {"sys_platform": "darwin"}
WINDOWS = {"sys_platform": "win32"}


# ---- pyproject declares the pin, explicitly and for Linux only -------------------------


def test_the_url_is_one_constant():
    assert deps.TORCH_CPU_INDEX == URL


def test_pyproject_declares_the_cpu_index_as_explicit():
    """`explicit = true` is the whole safety story on the lock side: the mirror hosts
    numpy, setuptools and requests too, and only an explicit index is prevented from
    ever serving them."""
    indexes = PYPROJECT["tool"]["uv"]["index"]
    cpu = [i for i in indexes if i.get("url") == URL]
    assert len(cpu) == 1, f"expected exactly one [[tool.uv.index]] for {URL}, got {indexes}"
    assert cpu[0]["explicit"] is True
    assert cpu[0]["name"] == "pytorch-cpu"


@pytest.mark.parametrize("package", ["torch", "torchaudio"])
def test_the_torch_stack_is_sourced_from_the_cpu_index_on_linux_only(package):
    sources = PYPROJECT["tool"]["uv"]["sources"][package]
    assert isinstance(sources, list) and len(sources) == 1, sources
    (source,) = sources
    assert source["index"] == "pytorch-cpu"
    assert re.fullmatch(r"sys_platform\s*==\s*['\"]linux['\"]", source["marker"]), (
        f"{package}: the marker must be exactly Linux -- PyPI's macOS wheels are already "
        f"CPU-only, and Windows stays on PyPI (ADR-028 Q2: torch's libiomp5md.dll clashes "
        f"with ctranslate2's, so there is no Windows voiceprint pack to protect)"
    )


@pytest.mark.parametrize("extra", ["voiceprint", "all"])
def test_the_extra_anchors_torch_so_the_source_can_apply(extra):
    """uv applies a `[tool.uv.sources]` entry only to a *direct* dependency. Measured on
    uv 0.12.21: source declared, torch absent from every extra, `uv lock
    --upgrade-package torch` re-resolved torch from pypi.org -- CUDA, 15 `nvidia-*`,
    no warning. torch and torchaudio are speechbrain's own requirements; they are
    repeated in the extra purely to anchor the index, so "tidying" them away reopens
    the 4.22 GB without any test but this one noticing."""
    names = {
        re.split(r"[<>=!~\[; ]", req, maxsplit=1)[0].strip().lower()
        for req in PYPROJECT["project"]["optional-dependencies"][extra]
    }
    assert {"torch", "torchaudio"} <= names, f"[{extra}] no longer anchors torch: {sorted(names)}"


def test_nothing_else_is_sourced_from_the_cpu_index():
    """The leak the resemblyzer comment in pyproject.toml documents: a per-extra decision
    is universal in `uv.lock`. Keep the mirror to the two packages it exists for."""
    sources = PYPROJECT["tool"]["uv"]["sources"]
    routed = {
        name
        for name, specs in sources.items()
        for spec in (specs if isinstance(specs, list) else [specs])
        if spec.get("index") == "pytorch-cpu"
    }
    assert routed <= {"torch", "torchaudio", "torchvision"}, routed


# ---- uv.lock actually resolved that way ---------------------------------------------------


def _blocks(name: str) -> list[str]:
    return [
        b for b in LOCK.split("\n[[package]]\n")
        if re.search(rf'^name = "{re.escape(name)}"$', b, re.M)
    ]


@pytest.mark.parametrize("package", ["torch", "torchaudio"])
def test_the_lock_has_a_linux_fork_of_torch_from_the_cpu_index(package):
    blocks = _blocks(package)
    assert blocks, f"{package} is not in uv.lock at all"
    cpu = [b for b in blocks if f'source = {{ registry = "{URL}" }}' in b]
    assert cpu, f"no {package} block in uv.lock comes from {URL}; run `uv lock`"
    for block in cpu:
        assert "+cpu" in block, f"the {URL} fork of {package} is not a +cpu build:\n{block[:400]}"
        assert "nvidia-" not in block, f"the CPU fork of {package} still depends on nvidia-*"
        assert "sys_platform == 'linux'" in block, (
            f"the CPU fork of {package} carries no Linux resolution marker"
        )


@pytest.mark.parametrize("package", ["torch", "torchaudio"])
def test_no_pypi_fork_of_torch_is_selected_on_linux(package):
    """The PyPI block may remain for macOS and Windows; none of its markers may be Linux."""
    for block in _blocks(package):
        if 'source = { registry = "https://pypi.org/simple" }' not in block:
            continue
        markers = re.findall(r'^resolution-markers = \[(.*?)\]', block, re.S | re.M)
        assert markers, (
            f"a PyPI {package} block has no resolution-markers, so it applies everywhere "
            f"including Linux"
        )
        for group in markers:
            for marker in re.findall(r'"([^"]+)"', group):
                assert "sys_platform == 'linux'" not in marker, (
                    f"PyPI {package} is still selected on Linux: {marker}"
                )


def test_no_nvidia_distribution_remains_in_the_lock():
    """torch's CUDA dependencies are Linux-x86_64-only, so once Linux is on the CPU
    index nothing in the whole development closure can pull them."""
    nvidia = re.findall(r'^name = "(nvidia-[^"]+)"$', LOCK, re.M)
    assert nvidia == [], f"uv.lock still resolves {len(nvidia)} nvidia-* packages: {nvidia}"


# ---- deps.py: the installed copy never sees the lock, so the argv carries the pin ---------


def test_the_stack_is_recognised_by_distribution_name():
    assert deps.pulls_torch(["speechbrain>=1.1"])
    assert deps.pulls_torch(["torch==2.14.1+cpu"])  # the undo path restores exact versions
    assert deps.pulls_torch(["pyannote.audio>=4.0.7"])
    assert deps.pulls_torch(["resemblyzer>=0.1.4"])
    assert deps.pulls_torch(["onnx-asr[cpu,hub]>=0.12", "torchaudio>=2"])
    assert not deps.pulls_torch(["onnx-asr[cpu,hub]>=0.12"])
    assert not deps.pulls_torch(["torchy>=1"])  # a prefix is not a match
    assert not deps.pulls_torch([])


def test_uv_install_on_linux_carries_the_index_and_the_best_match_strategy(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/uv")
    cmd = deps.install_command(["speechbrain>=1.1"], environment=LINUX)
    assert cmd == [
        "uv", "pip", "install", "--python", sys.executable,
        "--index", URL, "--index-strategy", "unsafe-best-match",
        "speechbrain>=1.1",
    ]


def test_pip_install_on_linux_carries_the_extra_index(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)
    cmd = deps.install_command(["speechbrain>=1.1"], environment=LINUX)
    assert cmd == [
        sys.executable, "-m", "pip", "install", "--extra-index-url", URL, "speechbrain>=1.1",
    ]


@pytest.mark.parametrize("environment", [MACOS, WINDOWS], ids=["macos", "windows"])
@pytest.mark.parametrize("uv", [True, False], ids=["uv", "pip"])
def test_other_platforms_stay_on_pypi(monkeypatch, environment, uv):
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/uv" if uv else None)
    cmd = deps.install_command(["speechbrain>=1.1"], environment=environment)
    assert URL not in cmd
    assert "--index-strategy" not in cmd and "--extra-index-url" not in cmd


@pytest.mark.parametrize("uv", [True, False], ids=["uv", "pip"])
def test_a_feature_without_torch_never_sees_the_mirror(monkeypatch, uv):
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/uv" if uv else None)
    cmd = deps.install_command(["onnx-asr[cpu,hub]>=0.12"], environment=LINUX)
    assert URL not in cmd
    assert "--index-strategy" not in cmd and "--extra-index-url" not in cmd


def test_the_index_rides_with_the_constraint_and_the_preflight_still_finds_it(
    monkeypatch, tmp_path
):
    """`_preflight` inserts `--dry-run` at `cmd.index("--constraint")`; the new flags
    must not move that marker out from under it, and the undo path (`--no-deps`,
    exact `+cpu` versions) must be able to fetch from the mirror."""
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/uv")
    c = tmp_path / "c.txt"
    cmd = deps.install_command(["speechbrain>=1.1"], constraints=c, environment=LINUX)
    assert cmd.index("--index") < cmd.index("--constraint") < cmd.index("speechbrain>=1.1")
    cmd.insert(cmd.index("--constraint"), "--dry-run")
    assert cmd[-3:] == ["--constraint", str(c), "speechbrain>=1.1"]
    undo = deps.install_command(["torch==2.14.1+cpu"], no_deps=True, environment=LINUX)
    assert "--index" in undo and "--no-deps" in undo


def test_the_uv_tool_receipt_path_carries_the_index_too():
    """`uv tool install --with …` is how most installs here get a feature, and the
    receipt records `index` and `index-strategy` under `[tool.options]` (checked
    against uv 0.12.21), so the next `uv tool upgrade` keeps torch on the CPU build.
    It must be computed over the *merged* with-list: enabling an unrelated feature
    after voiceprint re-issues the whole list, and dropping the index there would
    re-resolve torch from PyPI -- the CUDA build -- on that upgrade."""
    cmd = deps._merged_install_argv(
        "yazses==2.43.2", ["speechbrain>=1.1"], ["onnx-asr>=0.12"], environment=LINUX
    )
    assert cmd[-5:] == ["--index", URL, "--index-strategy", "unsafe-best-match", "yazses==2.43.2"]
    assert deps._merged_install_argv(
        "yazses", [], ["onnx-asr>=0.12"], environment=LINUX
    ) == ["uv", "tool", "install", "--with", "onnx-asr>=0.12", "yazses"]
    assert URL not in deps._merged_install_argv(
        "yazses", ["speechbrain>=1.1"], ["onnx-asr>=0.12"], environment=MACOS
    )


def test_the_pipx_channel_passes_the_index_as_the_one_pip_argument_it_keeps():
    """pipx stores and replays `--pip-args` on `pipx reinstall`; for a permanent index
    that replay is the point -- without it the reinstall resolves CUDA torch."""
    cmd = deps.pipx_inject_command("/v", ["speechbrain>=1.1"], environment=LINUX)
    assert cmd == ["pipx", "inject", "/v", "speechbrain>=1.1", "--pip-args", f"--extra-index-url {URL}"]
    assert deps.pipx_inject_command("/v", ["onnx-asr>=0.12"], environment=LINUX) == [
        "pipx", "inject", "/v", "onnx-asr>=0.12",
    ]
    assert "--pip-args" not in deps.pipx_inject_command("/v", ["speechbrain>=1.1"], environment=MACOS)


# ---- the inventory says where the bytes come from -----------------------------------------


def test_adr_019_names_the_second_host_for_deps_py():
    """An extra index is the same primitive (a spawned installer) reaching a NEW host.
    ADR-019's table names destinations; this row must name both."""
    adr = (ROOT / "design/adr/adr-019-egress-inventory-and-escalation.md").read_text(
        encoding="utf-8"
    )
    row = next(line for line in adr.splitlines() if line.startswith("| `system/deps.py` |"))
    assert "download.pytorch.org" in row, row
