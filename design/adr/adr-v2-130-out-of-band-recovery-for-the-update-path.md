# ADR-v2-130 — A repair to the update path needs a delivery route that does not depend on the update path

**Status:** Accepted (2026-08-15) · implemented in the same change (`0ddac30`)
**Context links:** [[adr-011]] (on-device, zero telemetry — constrains what a recovery
route may do), [[adr-019-egress-inventory-and-escalation]] (the update check is one of the
five *fetch* connections it enumerates)

## Context

`06c6d1b` fixed a real, reported failure: `yazses update` and the tray's **Install now**
both treated an exit code of `0` as proof the upgrade had happened. `uv tool upgrade`
prints `Nothing to upgrade` and exits 0 when the tool was installed with an exact version
pin, so an install offered 2.19.0 → 2.20.0 reported *"Update installed. Restart the
daemon"*, was restarted, and came back on 2.19.0 — repeatedly, with nothing on screen to
explain it. `run_upgrade_checked()` now re-reads the installed version out of process
instead of trusting the exit status.

That repair is correct and it is not sufficient, because of where it lives.

**The fix ships inside the client, and the client is the thing that cannot update
itself.** Whoever is stuck on the pinned install is, by definition, running the build
without `run_upgrade_checked()`. They will never see its diagnosis, never see
`pinned_install_hint()`, and every further improvement to those surfaces is invisible to
exactly the population that needs it. The failure is also self-concealing: it *reports
success*, so it generates no support request and no issue. There is no signal that would
tell us how many installs are sitting in it.

This generalizes past the updater. Any mechanism that delivers its own repairs — an
installer, a bootstrap script, an auto-update channel, a migration that rewrites the thing
performing the migration — has the same structure: the cohort that needs version N+1 is
reachable only by whatever N already contains, or by something outside the mechanism
entirely.

## Decision

**Every repair to a delivery mechanism must have at least one recovery route whose success
does not traverse that mechanism.** For the update path, three concrete consequences:

1. **A stable page, not only a message.** `updater.RECOVERY_URL` names
   `docs/how-to/update-did-nothing.md`, and every install method's `pinned_install_hint()`
   ends there. The URL is chosen over a longer in-client message deliberately: a message
   compiled into a released build is frozen at the moment it shipped, and the build
   carrying it is the build that cannot be updated. **The page is the only part of the
   answer that stays correctable afterwards.**
2. **Every method gets a route, not just the one the bug was reported on.** Before this,
   only `uv` had a real way out; `pip`, `pipx`, `snap` and the Windows channels fell
   through to *"Run it in a terminal to see what it reported"* — addressed to someone who
   had just run it and been told nothing.
3. **Only verified commands are quoted.** `pip --force-reinstall` and `snap refresh
   --unhold` were checked against the real tools. A method whose reinstall command is not
   verified gets the page instead of a plausible flag, because **a guessed command that
   also silently does nothing reproduces the exact failure this ADR exists to correct.**
   The Windows installer channel is quoted no command at all — that upgrade is a download.

Both halves are pinned by `tests/test_updater.py`: every install method's hint must name
the recovery page, and `RECOVERY_URL` must resolve to a page that exists under `docs/`.

## Consequences

- A URL compiled into a released binary is a **load-bearing artifact**. It is quoted at
  the moment the user has already been misled once, and nothing downstream can correct it,
  so the test maps it back to a source file rather than trusting it by inspection —
  including the `.html` suffix, since `use_directory_urls: false` in `mkdocs.yml` makes
  the trailing-slash form a 404. That mistake was made and caught by the test while writing
  this change.
- `docs/how-to/update-did-nothing.md` must not be renamed or moved without updating
  `RECOVERY_URL`, and old released clients will keep pointing at that exact path
  indefinitely. **Treat it as a permanent URL.** If it must move, leave a redirect.
- The recovery page is plain documentation on the existing site. It adds **no outbound
  connection** and does not touch the ADR-019 inventory: nothing in `src/yazses/` fetches
  it, it is only printed for a human to open.
- This does not, and cannot, reach an install whose user never runs the update again.
  Out-of-band means "not through the broken mechanism", not "guaranteed delivery". The
  claim here is bounded to making the route *exist and be findable*.

## Rejected

- **Improve the in-client message only.** The dominant failure mode is a client that
  predates any such improvement. This is the alternative that feels sufficient and is
  precisely the one the ADR rules out.
- **Have the daemon phone home to detect stuck installs.** It would identify the cohort
  directly, and it violates [[adr-011]] (zero telemetry, on-device by default). The
  self-concealing nature of the bug is not a licence to add reporting.
- **Auto-run the reinstall when the version is unchanged.** Reinstalling a user's tool
  without asking — with the extras question live, where a wrong choice silently removes
  the tray and the overlay — is a destructive action taken on an inference. It is offered
  as a command to run, not performed.
- **Quote a best-guess reinstall command for the unverified methods.** Better coverage on
  paper; the failure being repaired is precisely a command that runs, does nothing, and
  says it worked.
