"""Every `docker run ... yazses <args>` printed in the docs must be a real command.

Four pages invited the reader to *prove* the offline claim by running one container
command, and the command could not work. It was written as::

    docker run --rm --network none -v yazses-models:/models -v "$PWD:/data" \\
        yazses jfk.wav

Two independent faults, either of which is fatal:

1. **No subcommand.** The image's ``ENTRYPOINT`` is ``yazses``, so the container ran
   ``yazses jfk.wav`` -- and ``jfk.wav`` is not a command. Click exits 2 without
   transcribing anything.
2. **The cache volume was mounted where nothing looks.** The image sets
   ``XDG_CACHE_HOME=/home/yazses/.cache``; ``/models`` appears nowhere in the
   Dockerfile. So the named volume cached nothing, and every run re-downloaded the
   model -- which under ``--network none`` cannot happen at all.

The pages carrying it were the ones where being wrong costs the most: the privacy
statement, the cost page, "try without installing", and the page written for people
whose work is confidential. `docs/docker.md` and the README had it right the whole
time, which is why nothing noticed: the correct form existed a file away.

These tests parse the shell blocks and resolve each invocation against the real CLI
and against the Dockerfile's own environment, so neither fault can return by
copy-paste from an older revision.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import click
import pytest
import typer.main

from yazses.cli import app

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "packaging" / "docker" / "Dockerfile"

#: Docker flags that swallow the next token, so the token after them is never the
#: image name. `--flag=value` needs no entry here.
VALUE_FLAGS = {
    "-v", "--volume", "--mount", "-e", "--env", "--env-file", "-u", "--user",
    "-w", "--workdir", "--name", "--network", "--entrypoint", "-p", "--publish",
    "--device", "--add-host", "--label", "-l", "--platform", "--gpus",
}

#: Where the docs live. The README is included because it carries the headline
#: example, and a wrong headline is the most expensive kind.
DOC_ROOTS = (ROOT / "docs", ROOT / "README.md")


def _dockerfile_cache_dir() -> str:
    """The cache path the image actually uses, read from the image definition.

    Derived rather than restated: a constant written here would agree with the docs
    and disagree with the container, which is the failure being guarded against.
    """
    text = DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"^\s*XDG_CACHE_HOME=(\S+)", text, re.MULTILINE)
    assert match, "the Dockerfile no longer sets XDG_CACHE_HOME; this guard is blind"
    return match.group(1).rstrip("\\").strip()


def _shell_lines() -> list[tuple[Path, int, str]]:
    """Fenced shell blocks, with `\\` continuations joined into one logical line."""
    out: list[tuple[Path, int, str]] = []
    files: list[Path] = []
    for root in DOC_ROOTS:
        files += sorted(root.rglob("*.md")) if root.is_dir() else [root]
    for path in files:
        in_fence = False
        buf, start = "", 0
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = raw.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence and bool(
                    re.match(r"```(sh|bash|shell|console)?$", stripped)
                )
                buf = ""
                continue
            if not in_fence:
                continue
            if not buf:
                start = number
            if stripped.endswith("\\"):
                buf += stripped[:-1] + " "
                continue
            out.append((path, start, (buf + stripped).strip()))
            buf = ""
    return out


def _docker_runs() -> list[tuple[Path, int, list[str], list[str]]]:
    """(file, line, mount specs, args after the image) for each `docker run` of ours."""
    found = []
    for path, number, line in _shell_lines():
        if not re.match(r"^\$?\s*docker\s+run\b", line):
            continue
        try:
            tokens = shlex.split(line.lstrip("$ "))
        except ValueError:
            continue
        tokens = tokens[2:]  # drop `docker run`
        mounts, image_at, skip = [], None, False
        for index, token in enumerate(tokens):
            if skip:
                skip = False
                if tokens[index - 1] in {"-v", "--volume"}:
                    mounts.append(token)
                continue
            if token.startswith("-"):
                if "=" in token:
                    flag, _, value = token.partition("=")
                    if flag in {"-v", "--volume"}:
                        mounts.append(value)
                elif token in VALUE_FLAGS:
                    skip = True
                continue
            image_at = index
            break
        if image_at is None:
            continue
        image = tokens[image_at]
        if not re.fullmatch(r"(ghcr\.io/mskazemi/)?yazses(:[\w.-]+)?", image):
            continue
        found.append((path, number, mounts, tokens[image_at + 1:]))
    return found


def _resolve(args: list[str]) -> tuple[object | None, list[str]]:
    """Walk the real command tree as far as the tokens name subcommands.

    Duck-typed on ``get_command`` rather than ``isinstance(node, click.Group)``:
    this Typer ships its own ``typer._click`` core, so a ``TyperGroup`` is not a
    ``click.Group`` and the isinstance form silently never descends -- every
    example then resolves to the root and every flag looks unknown.
    """
    node: object = typer.main.get_command(app)
    rest = list(args)
    while rest and hasattr(node, "get_command"):
        child = node.get_command(click.Context(node), rest[0])  # type: ignore[attr-defined]
        if child is None:
            return (None, rest)
        node = child
        rest.pop(0)
    return (node, rest)


CASES = _docker_runs()


def test_the_docs_still_contain_container_examples() -> None:
    """Guards against every test below passing on a corpus of nothing."""
    assert CASES, "no `docker run ... yazses` examples found; this file checks nothing"


@pytest.mark.parametrize(
    "case", CASES, ids=lambda c: f"{c[0].name}:{c[1]}",
)
def test_the_documented_invocation_names_a_real_command(
    case: tuple[Path, int, list[str], list[str]],
) -> None:
    """`ENTRYPOINT ["yazses"]` means the first argument has to be a subcommand."""
    path, number, _, args = case
    if not args or args[0] in {"--help", "--version"}:
        return
    command, _rest = _resolve(args)
    assert command is not None, (
        f"{path.relative_to(ROOT)}:{number} runs the image as `yazses {' '.join(args)}`, "
        f"and `{args[0]}` is not a YazSes command. The image's ENTRYPOINT is `yazses`, "
        "so the example needs the subcommand spelled out -- `transcribe <file>` -- or "
        "it exits 2 having transcribed nothing."
    )


@pytest.mark.parametrize(
    "case", CASES, ids=lambda c: f"{c[0].name}:{c[1]}",
)
def test_the_documented_flags_exist_on_that_command(
    case: tuple[Path, int, list[str], list[str]],
) -> None:
    path, number, _, args = case
    command, rest = _resolve(args)
    if command is None:
        pytest.skip("covered by the command-name test")
    # `get_params` rather than `.params`: Click synthesises `--help` at parse time,
    # so it is absent from the declared list and a documented `--help` would read as
    # an unknown option.
    params = command.get_params(click.Context(command))  # type: ignore[attr-defined]
    known = {opt for param in params for opt in param.opts + param.secondary_opts}
    for token in rest:
        if not token.startswith("-") or token == "--":
            continue
        name = token.partition("=")[0]
        assert name in known, (
            f"{path.relative_to(ROOT)}:{number} passes `{name}` to "
            f"`{command.name}`, which has no such option."
        )


@pytest.mark.parametrize(
    "case", CASES, ids=lambda c: f"{c[0].name}:{c[1]}",
)
def test_the_model_cache_volume_is_mounted_where_the_image_looks(
    case: tuple[Path, int, list[str], list[str]],
) -> None:
    """A named volume for the models is only a cache if it is mounted on the path
    the image reads. Mounted anywhere else it silently caches nothing, and the
    `--network none` demonstration then cannot work at all."""
    path, number, mounts, _ = case
    cache_dir = _dockerfile_cache_dir()
    for spec in mounts:
        source, _, remainder = spec.partition(":")
        if "models" not in source or source.startswith(("/", ".", "$")):
            continue  # a bind mount of the user's own directory, not the cache volume
        target = remainder.split(":")[0]
        assert target == cache_dir, (
            f"{path.relative_to(ROOT)}:{number} mounts the model-cache volume "
            f"`{source}` at `{target}`, but the image caches into `{cache_dir}` "
            f"(XDG_CACHE_HOME in {DOCKERFILE.relative_to(ROOT)}). Mounted there it "
            "caches nothing: every run re-downloads the model, and a `--network none` "
            "run has no way to get one."
        )
