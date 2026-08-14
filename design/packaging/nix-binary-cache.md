# Nix: never pin a non-default interpreter — it silently disables the binary cache

**Status:** the cache bug is fixed and verified (`flake.nix` uses `pkgs.python3`,
`flake.lock` is committed, and a preflight guard in `packaging/nix/build-and-test.sh`
refuses an unintended source build). The flake still does **not** produce a package —
it now fails in about five minutes on an unrelated, pre-existing defect, described in
"Still broken: typer" at the bottom. That is the intended outcome of this change: fail
fast and loudly instead of burning four hours first.

This file exists because the failure is invisible. Nothing errors, nothing warns, and
the flake is *correct* — it just takes four hours instead of four minutes and pins every
core of the build machine at 100% while it does. If you are reading this because a Nix
build is inexplicably compiling C++, start here.

## What happened

Running the documented verification command

```
docker run --rm -v "$PWD:/host:ro" nixos/nix /host/packaging/nix/build-and-test.sh
```

compiled **PyTorch from source**. It ran 3 h 37 min across all 20 cores of the author's
laptop (i7-1370P) before being stopped, and had not finished. The container was
`--rm` with no persistent `/nix`, so all of that work was discarded on stop.

## Why

Two independent facts combine into the trap.

1. **`onnx-asr` depends on torch — in nixpkgs, but not in pip.** `pyproject.toml` says
   "no torch" in several places and is right about the *pip* graph: the ONNX runtime path
   deliberately avoids torch. But nixpkgs packages `onnxscript` with torch as a
   dependency, and `onnx-asr` propagates `onnxscript`. `nix why-depends` shows it plainly:

   ```
   yazses-2.18.2.drv
   └── python3.12-onnx-asr-0.12.0.drv
       └── python3.12-onnxscript-0.7.1.drv
           └── python3.12-torch-2.12.0.drv
   ```

   So torch is in the Nix closure whether or not it is in the pip closure. That alone is
   fine — torch is a large but ordinary cached download.

2. **`flake.nix` pinned `pkgs.python312`, and Hydra only caches the *default* Python.**
   This is the actual defect. nixpkgs' build farm builds the default `python3` package
   set; other interpreters are evaluated but very largely not built. At the pinned
   nixpkgs revision the default `python3` was **3.14.7**, so `python312Packages.*` was
   outside the cache. Measured against `cache.nixos.org` at revision `0e251e24`:

   | attribute | cached? |
   |---|---|
   | `python312Packages.torch` | **no — source build** |
   | `python313Packages.torch` | yes |
   | `python3Packages.torch` (3.14, default) | yes |

   And across yazses' full declared dependency list (12 packages):

   | package set | uncached |
   |---|---|
   | `python312Packages` | **3** — `faster-whisper`, `onnx-asr`, `evdev` |
   | `python313Packages` | 0 |
   | `python3Packages` (default) | 0 |

   `onnx-asr` being uncached is what dragged the uncached torch in with it.

A contributing factor: there was **no committed `flake.lock`**, and the script passes
`--no-write-lock-file`, so `nixpkgs.url = ".../nixos-unstable"` was re-resolved on every
run. Even with the interpreter fixed, that makes the build non-reproducible and can drift
onto a revision the cache has not caught up with.

## The fix

- `flake.nix` uses **`pkgs.python3`**, the default interpreter, never a pinned
  `pkgs.python312`. Verified: 0 dependencies require a source build.
- **`flake.lock` is committed**, pinned to nixpkgs `0e251e24` — the revision whose cache
  coverage is measured above. The build is now reproducible instead of tracking a moving
  branch.
- `packaging/nix/build-and-test.sh` runs a **preflight**: `nix build --dry-run`, then
  counts derivations that would be *built* (`.drv` paths) rather than *fetched* (plain
  store paths), excluding yazses itself. If any dependency would be compiled it prints
  them and **exits non-zero** instead of starting. Override deliberately with
  `ALLOW_SOURCE_BUILD=1`, which also caps the build to half the machine's cores
  (`BUILD_CORES=N` to choose) so an intentional source build leaves the machine usable.

## Rules for anyone touching flake.nix

1. **Use `pkgs.python3`.** If you ever need a specific interpreter, you are opting out of
   the binary cache — measure it first and say so in a comment.
2. **Keep `flake.lock` committed**, and when bumping it, re-check cache coverage before
   pushing. The one-liner that does it:

   ```sh
   docker run --rm nixos/nix sh -lc '
     export NIX_CONFIG="experimental-features = nix-command flakes"
     N=github:NixOS/nixpkgs/<rev>
     OUT=$(nix eval --raw $N#python3Packages.torch.outPath)
     nix path-info --store https://cache.nixos.org "$OUT" >/dev/null 2>&1 \
       && echo CACHED || echo "NOT CACHED — will compile"'
   ```

3. **Give the container a persistent store** when you do accept a real build, so stopping
   it does not throw the work away:

   ```
   docker run --rm -v "$PWD:/host:ro" -v yazses-nix-store:/nix nixos/nix \
       /host/packaging/nix/build-and-test.sh
   ```

4. Per `packaging/AGENTS.md`: a Nix change is verified by *running* this script, not by
   reading the flake. Evaluation succeeding does not mean the package builds.

## Still broken: typer (separate defect, found by this fix)

With the cache bug fixed, the build gets far enough to reveal the next one and fails:

```
==> preflight: is the closure cached?
    all cached — nothing will be compiled
==> nix build .#yazses
    Checking runtime dependencies for yazses-2.18.2-py3-none-any.whl
      - typer>=0.26.8 not satisfied by version 0.25.1
```

`pyproject.toml:58` requires `typer>=0.26.8`. nixpkgs at the pinned revision ships
**0.25.1 in every Python package set** — 3.12, 3.13 and the default alike:

| attribute | version |
|---|---|
| `python312Packages.typer` | 0.25.1 |
| `python313Packages.typer` | 0.25.1 |
| `python3Packages.typer` | 0.25.1 |

So this is **not** caused by moving to `pkgs.python3`; it would have failed identically
on 3.12 — the original run simply never got here, because it spent four hours compiling
torch first. It means the flake has never produced an installable package, even though
its header says evaluation passes. `nix flake check --no-build` genuinely does pass;
evaluation is not a build.

Not fixed here, because the right resolution is a maintainer call and none of the options
is free:

- **Relax it for the Nix build** (`pythonRelaxDeps = [ "typer" ]`). One line, keeps the
  cache. But `typer>=0.26.8` arrived in `60b2641` with no recorded rationale, so nobody
  knows whether the code actually uses a post-0.25.1 feature. Testable: relax it and let
  the bundled offline suite run — if `pytestCheckHook` passes, that is real evidence.
- **Override typer to a newer version in the flake.** Correct on paper, but a
  `packageOverrides` on the Python set risks invalidating the cached closure and
  reintroducing exactly the mass-rebuild this document is about. Verify with the
  preflight before accepting it.
- **Wait for nixpkgs to ship a newer typer**, then bump `flake.lock`. Zero risk, no
  timeline.
- **Lower the floor in `pyproject.toml`** if 0.25.1 really is sufficient — but that is a
  change to the real dependency contract, not a packaging tweak, and it conflicts with
  the project's "latest stable" dependency policy.

## Note on the interpreter change

Moving from 3.12 to the default `python3` (3.14) is what buys the cache. `pyproject.toml`
declares `requires-python = ">=3.11"`, so this is inside the supported range, but the
classifiers list only 3.11 and 3.12 — if 3.14 becomes the tested configuration, add the
classifier. The Nix package is not what defines yazses' supported Python versions; pip
and the CI matrix are.
