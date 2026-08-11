# packaging/ — scoped agent notes

Read the root [`AGENTS.md`](../AGENTS.md) first; it is canonical and everything in it
still applies. This file only records where packaging genuinely differs, and it is short
on purpose — a second copy of the project rules would become a second, divergent set.

## You almost certainly cannot verify a change here

The rest of the repository has a fully offline test suite. Packaging does not. A change to
a PKGBUILD, a Homebrew formula, a winget manifest or a PyInstaller spec is verified by
**building the artifact on that platform and installing it**, which usually means a
machine or CI runner you do not have.

So: do not report a packaging change as working because tests passed. They do not test
this. Say plainly what you did and did not verify — an honest "manifest updated, not
built" is useful; an implied success is not.

## Release credentials are not in this repository, by design

Signing keys, certificates and store tokens live in GitHub Actions secrets and in the
maintainer's password manager. The procedures that use them are kept out of the public
repository deliberately.

If a task appears to need a credential, a signing identity, a store account or a publish
step, **stop and hand it to the maintainer**. Do not add a secret to a manifest, a
workflow, an environment file or a comment, and do not invent a placeholder that looks
like a real one.

## Versions appear in many files and must agree

A release version is written into `pyproject.toml`, winget manifests, Homebrew formulae,
the Arch PKGBUILD and the installer scripts. Changing one and not the others produces a
package that installs the wrong thing. If you bump a version, grep for the old one across
the whole repository and fix every occurrence in the same change.

Old versions under `winget/manifests/**` are history and stay — do not tidy them away.

## Adding a channel

New packaging channels are a maintainer decision, not a contribution someone can land
unilaterally: each one is a promise to keep publishing, and an abandoned channel installs
a stale, insecure version for years. Propose it in an issue first.

Verifying an existing channel is the opposite — genuinely useful, needs no credentials,
and there are open tasks for it in
[`../campaign/generated/open-tasks.md`](../campaign/generated/open-tasks.md).
