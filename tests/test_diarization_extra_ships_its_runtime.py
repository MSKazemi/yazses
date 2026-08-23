"""The `diarization` extra must install sherpa-onnx's native libraries too.

sherpa-onnx is split across two distributions: `sherpa-onnx` holds the Python
bindings, `sherpa-onnx-core` holds `libonnxruntime.so` and the two sherpa `.so`
files the bindings link against. The dependency between them is declared in the
**wheel's** METADATA and **not** in the sdist's PKG-INFO, and uv resolved the
sdist's view while installing the wheel -- so `uv.lock` recorded `sherpa-onnx`
with no dependencies at all and `sherpa-onnx-core` appeared nowhere in it.

The result was that `uv sync --extra diarization` installed bindings with no
runtime under them, on every platform, and `import sherpa_onnx` raised
`ImportError: libonnxruntime.so: cannot open shared object file`.

Two layers then hid it:

* `recimport.factory.build_diarizer` catches the failure and returns None, which
  is correct behaviour -- it degrades to an unattributed transcript rather than
  crashing a meeting -- but it means the only symptom is a log line.
* `recimport.factory.diarization_status` decides "the extra is installed" with
  `importlib.util.find_spec`, which answers *is it on disk*, not *can it import*.
  It found the package, reported `ready`, and so `meeting start`'s warning --
  whose entire purpose is that there is never a silent un-attributed transcript --
  stayed silent.

No CI job installs this extra, so nothing exercised the combination. This guard is
static instead: it reads the manifest, so it runs on every job on every platform
whether or not the extra is installed.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# The bindings package -> the distribution carrying its native libraries.
_NATIVE_RUNTIME = {"sherpa-onnx": "sherpa-onnx-core"}


def _requirement_name(spec: str) -> str:
    """`sherpa-onnx>=1.13.6` -> `sherpa-onnx`; `onnx-asr[cpu,hub]>=0.12` -> `onnx-asr`."""
    for sep in ("[", ">", "<", "=", "!", "~", ";", " "):
        spec = spec.split(sep, 1)[0]
    return spec.strip().lower().replace("_", "-")


@pytest.fixture(scope="module")
def extras() -> dict[str, list[str]]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]


@pytest.mark.parametrize(("bindings", "runtime"), sorted(_NATIVE_RUNTIME.items()))
def test_every_extra_naming_the_bindings_also_names_the_runtime(
    extras, bindings, runtime
):
    offenders = []
    for name, specs in extras.items():
        present = {_requirement_name(s) for s in specs}
        if bindings in present and runtime not in present:
            offenders.append(name)
    assert not offenders, (
        f"extras {offenders} install {bindings!r} without {runtime!r}, which carries "
        f"its native libraries — `import {bindings.replace('-', '_')}` will raise "
        f"ImportError at runtime and the diarizer will silently degrade to an "
        f"unattributed transcript"
    )


@pytest.mark.parametrize(("bindings", "runtime"), sorted(_NATIVE_RUNTIME.items()))
def test_the_lockfile_carries_the_native_runtime(bindings, runtime):
    """The manifest is only half of it — the lock is what `uv sync` installs from."""
    lock = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    assert f'name = "{runtime}"' in lock, (
        f"{runtime!r} is absent from uv.lock, so `uv sync` installs {bindings!r} "
        f"without the shared libraries it links against. Re-run `uv lock`."
    )
