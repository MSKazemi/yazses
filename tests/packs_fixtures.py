"""Synthetic add-on packs for the ADR-028 tests: indexes, manifests, real ZIPs, and a
fake ``PackRuntime``. Every pack here is built in ``tmp_path`` from a few bytes of
made-up Python; nothing is downloaded and no real wheel is involved."""
from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yazses.packs.abi import BaseIdentity
from yazses.packs.manifest import parse_index

BUILD_ID = "sha256:" + "a" * 64
OTHER_BUILD_ID = "sha256:" + "b" * 64
VERSION = "2.44.0"
PY = {"cache_tag": "cpython-312", "version": "3.12.9", "abi": "cp312"}
PLATFORM = "win-amd64"
ARCH = "x64"


def asset_name(name: str, version: str = VERSION) -> str:
    return f"YazSes-{version}-windows-{ARCH}-pack-{name}.yazpack"


def base(build_id: str = BUILD_ID, **over: str) -> BaseIdentity:
    fields = dict(
        build_id=build_id, cache_tag=PY["cache_tag"], python_version=PY["version"],
        platform=PLATFORM, arch=ARCH, app_version=VERSION,
    )
    fields.update(over)
    return BaseIdentity(**fields)


def manifest_dict(name: str = "parakeet", **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "format": 1,
        "name": name,
        "extra": name,
        "features": ["stt-parakeet"] if name == "parakeet" else [f"feat-{name}"],
        "app_version": VERSION,
        "base_build_id": BUILD_ID,
        "python": dict(PY),
        "platform": PLATFORM,
        "arch": ARCH,
        "distributions": [{"name": "onnx-asr", "version": "0.12.0"}],
        "entry_modules": [f"fakepkg_{name.replace('-', '_')}"],
        "native_dirs": [],
        "unpacked_bytes": 0,
        "files": 0,
    }
    data.update(over)
    return data


def entry_dict(name: str = "parakeet", **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": name,
        "asset": asset_name(name),
        "sha256": "c" * 64,
        "size": 312345,
        "unpacked_bytes": 1234567,
        "files": 210,
        "features": ["stt-parakeet"] if name == "parakeet" else [f"feat-{name}"],
    }
    data.update(over)
    return data


def index_dict(*entries: dict[str, Any], **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "format": 1,
        "app_version": VERSION,
        "base_build_id": BUILD_ID,
        "python": dict(PY),
        "platform": PLATFORM,
        "arch": ARCH,
        "packs": list(entries) if entries else [entry_dict()],
    }
    data.update(over)
    return data


@dataclass
class BuiltPack:
    path: Path
    sha256: str
    size: int
    unpacked: int
    files: int
    name: str
    manifest: dict[str, Any] = field(default_factory=dict)

    def entry(self, **over: Any) -> dict[str, Any]:
        return entry_dict(
            self.name, sha256=self.sha256, size=self.size,
            unpacked_bytes=self.unpacked, files=self.files,
            features=self.manifest["features"], **over,
        )

    def index(self, **over: Any):
        return parse_index(json.dumps(index_dict(self.entry(), **over)))


def payload_for(name: str = "parakeet") -> dict[str, bytes]:
    mod = f"fakepkg_{name.replace('-', '_')}"
    return {
        f"site/{mod}/__init__.py": f"VALUE = {name!r}\n".encode(),
        f"site/{mod}/core.py": b"def hello():\n    return 'hi'\n",
        f"site/{mod}-1.0.dist-info/METADATA": b"Name: fake\nVersion: 1.0\n",
        "LICENSES/fake.txt": b"MIT\n",
    }


def build_pack(
    out: Path,
    name: str = "parakeet",
    payload: dict[str, bytes] | None = None,
    *,
    manifest_over: dict[str, Any] | None = None,
    record_over: list[dict[str, Any]] | None = None,
    extra_members: dict[str, bytes] | None = None,
) -> BuiltPack:
    """A real ``.yazpack`` with a consistent pack.json and RECORD.json."""
    files = dict(payload if payload is not None else payload_for(name))
    record = [
        {"path": p, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
        for p, b in sorted(files.items())
    ]
    record_bytes = json.dumps({"format": 1, "files": record_over or record}).encode()
    # As scripts/build-packs.py does it: the counts cover EVERY member, pack.json and
    # RECORD.json included, so pack.json is computed to a fixed point.
    payload_bytes = sum(len(b) for b in files.values())
    guess = 0
    for _ in range(10):
        manifest = manifest_dict(
            name, files=len(files) + 2,
            unpacked_bytes=payload_bytes + len(record_bytes) + guess,
        )
        manifest.update(manifest_over or {})
        manifest_bytes = json.dumps(manifest).encode()
        if len(manifest_bytes) == guess or manifest_over and (
            "files" in manifest_over or "unpacked_bytes" in manifest_over
        ):
            break
        guess = len(manifest_bytes)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pack.json", manifest_bytes)
        zf.writestr("RECORD.json", record_bytes)
        for p, b in sorted(files.items()):
            zf.writestr(p, b)
        for p, b in (extra_members or {}).items():
            zf.writestr(p, b)
    data = out.read_bytes()
    return BuiltPack(
        path=out,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        unpacked=manifest["unpacked_bytes"],
        files=manifest["files"],
        name=name,
        manifest=manifest,
    )


class FakeRuntime:
    """Records every native directory added; elevation and support are settable."""

    def __init__(self, *, supported: bool = True, elevated: bool = False,
                 index_path: Path | None = None, fail_native: bool = False) -> None:
        self._supported = supported
        self._elevated = elevated
        self._index_path = index_path
        self._fail_native = fail_native
        self.native_dirs: list[Path] = []

    def supported(self) -> bool:
        return self._supported

    def is_elevated(self) -> bool:
        return self._elevated

    def add_native_dir(self, path: Path) -> object:
        if self._fail_native:
            raise OSError("refused by the fake")
        self.native_dirs.append(path)
        return ("handle", str(path))

    def embedded_index_path(self) -> Path | None:
        return self._index_path

    def probe_command(self, name: str, staged: Path) -> list[str] | None:
        return ["probe", name, str(staged)]
