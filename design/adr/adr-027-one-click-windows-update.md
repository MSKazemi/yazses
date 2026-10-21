# ADR-027 — One-click update on Windows: verify, hand off, relaunch

**Status:** Accepted (2026-10-20; revised the same day after review, see *Revision*)
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-019-egress-inventory-and-escalation]] (the egress rows this adds),
[[adr-011]] (nothing leaves the machine), [[adr-021-invest-in-error-cost]]

---

## Context

On Ubuntu, *Check for updates…* → *Install now* runs the package manager and the update
happens. On Windows the same click found the update and then told the user to open the
releases page, download `YazSes-<version>-windows-<arch>.exe` and run it. For a
non-technical user that is the hard part, and many uninstalled and reinstalled by hand.

`updater.upgrade_command("windows-installer")` answered `None` on purpose. The upgrade is
a downloaded binary, and running a fetched binary for the user needed a decision first.
`tray/updates.describe_update` said that in its docstring: "it needs the code-signing
question settled first". This ADR records that decision.

Three facts about Windows shape the design:

1. **An installer cannot replace files that a running process holds open.** The tray, the
   daemon and the CLI all run from `{app}` (`YazSesApp.exe`, `yazses-cli.exe`,
   `_internal\*.dll|*.pyd`). So YazSes cannot run the installer and wait for it.
2. **The Inno installer already upgrades in place.** `installer.iss` has a fixed `AppId`.
   `UsePreviousAppDir` and `UsePreviousPrivileges` default to yes, so a new installer
   reuses the old directory and install mode. Settings and models live outside `{app}`.
   No uninstall is ever needed.
3. **Chocolatey, winget and Scoop have the same problem.** Each ends by running the same
   Inno installer, or by extracting it over the app (Scoop, which also refuses to update
   while the app runs). Running their upgrade command from inside YazSes would kill the
   process that waits for its output.

## Decision

### When the update is offered at all (`installer_update.one_click_offer`)

Before the user is asked anything, all of these must hold. If one fails, the user gets the
reason and the manual steps, and the tray opens the releases page:

- **Strictly newer.** `updater.check_update` asks the GitHub release and the version must be
  strictly newer (`is_newer`). Drafts and prereleases are refused.
- **A covered method.** `windows-installer`, `choco`, `winget` or `scoop`. The **MSIX**
  package is its own method (`msix`), detected from the platform seam's
  `HostInfo.msix_packaged`, the same fact `cameraperm/matrix.py` uses. It gets Store /
  App Installer steps and no one-click. The `.exe` would install a second copy beside the
  package rather than update it.
- **Per-user install only** for `windows-installer`. `WindowsUpdateLauncher.install_scope`
  matches the running directory against the Inno uninstall key
  (`{AppId}_is1`, `Inno Setup: App Path`) under HKCU and HKLM. `"machine"` (all users) and
  `"unknown"` are refused (see *Trust model*).
- **The manager's own feed carries the version** for `choco` / `winget` / `scoop`.
  `choco search yazses --exact --limit-output`, `winget show --id MSKazemi.YazSes -e` and
  `scoop info yazses` are parsed by `parse_feed_version`. Chocolatey's moderated packages,
  winget's manifests and Scoop's bucket follow the GitHub tag, often by days. Offering 2.44.0
  when `choco upgrade` will say "nothing to do" is a false claim. An unreadable answer also
  means no offer.
- **From the CLI, with or without the tray** (revised 2026-10-21). The CLI cannot ask the
  tray to quit over IPC, so the first version refused while the tray ran. The tray
  autostarts at sign-in, so that refused almost every time. Now the tray's PID (the
  holder of `tray.lock`) joins the PIDs the job waits for, and the tray closes itself when
  it sees a `pending.json` written after it started by another process
  (`installer_update.handoff_started_elsewhere`, polled about once a second by
  `tray.app.UpdateHandoffWatch`). Closing runs the tray's `on_quit`, which stops its poll
  before sending `shutdown`, so the daemon is not respawned under the installer. The CLI
  waits up to 20 s for the tray to go, then sends `shutdown` itself. A lock held by a
  process that cannot be named (`holder_pid` = -1) is still refused, because the job could
  not wait for it. `tray.updates.hand_off_outside_tray` holds this sequence so a Settings
  window button can reuse it.

### What a confirmed click does

1. **Confirm:** a native Yes/No box (tray) or a prompt (CLI; `--yes` skips it). Only an
   explicit yes continues. If the box cannot be shown, the answer is no.
2. **Single-flight lock:** `update.lock` is created with `O_CREAT | O_EXCL` in the staging
   directory. A second click (two threads, or the tray and a terminal) is refused with
   "already in progress". A lock older than 2 h is from a dead attempt and is taken over.
   The detached job deletes the lock when it finishes. Python deletes it on any failure
   before the hand-off.
3. **Plan** (pure, `system/installer_update.py`). Pick `YazSes-<v>-windows-<arch>.exe` for
   the machine's native architecture (`IsWow64Process2`, then the environment). ARM64
   falls back to x64, which the `.iss` allows; x64 never takes arm64. The URL must parse as
   `https://github.com/MSKazemi/yazses/releases/download/<tag>/<that file>` on exactly
   `github.com`. A userinfo part, a port, a query, a `..` segment or an encoded slash is
   refused. The SHA-256 comes from the release's `SHA256SUMS.txt`, with exactly one entry
   required. If GitHub reports a `sha256:` digest for the asset, it must agree.
4. **Fetch with the right headers.** The REST API gets
   `Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2022-11-28`. Release
   assets get `application/octet-stream`. The first version of this module sent
   octet-stream to the API too. `api.github.com` answers that with **HTTP 415**, so every
   real attempt fell back to manual while every test passed: the tests injected an opener
   and never saw a real header. A test now captures the `Request` objects the default
   opener builds.
5. **Download** to `%TEMP%\yazses-update\` (per-user). The file is written to `.part` and
   renamed only after it verifies. Hard cap of 1 GiB, and never more than the size the
   release declares. Short reads are refused. 30 s read timeout, 30 min overall deadline.
   Redirects are followed only to https on `github.com` or `*.githubusercontent.com`.
6. **Verify before running.** The SHA-256 of the bytes written must match, or the file is
   deleted and the update refused.
7. **Hand off** (`platform/windows/update_handoff.py`, behind the `UpdateLauncher`
   Protocol). A detached Windows PowerShell job is started by absolute path with
   `-EncodedCommand`. That avoids a `.ps1` file, the execution policy, cmd's `%`/`&`
   parsing and the OEM code page. The job:
   - waits up to **300 s in total** for the tray, daemon and CLI PIDs to exit;
   - **aborts if any is still running** (exit `-3`). Nothing is installed: a daemon still
     saving a meeting must not be force-closed. There is no `/FORCECLOSEAPPLICATIONS`;
   - **re-checks the SHA-256** immediately before running;
   - runs `installer /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /CLOSEAPPLICATIONS
     /NORESTARTAPPLICATIONS /LOG=…`, never elevated;
   - records the exit code and deletes the installer and the lock;
   - **starts YazSes again whether or not the update worked**. If an old process is still
     running, the second tray finds the single-instance lock held and exits quietly.

   For choco, winget and Scoop the job runs `updater.upgrade_command(method)` plus the
   flags an unattended run needs, by absolute path. winget and Scoop are resolved from
   `PATH` and run unelevated, with output captured to the log. **Chocolatey** is the one
   elevated run (`-Verb RunAs`). Its `choco.exe` comes from the **machine** environment's
   `ChocolateyInstall` (HKLM), or the documented default `C:\ProgramData\chocolatey`.
   Never from this process's environment: a user-level variable is writable by any
   same-user process.
8. **Shut down:** after a successful hand-off, the tray quits and its `on_quit` sends the
   daemon `shutdown`. The CLI first waits for a running tray to close itself (see above),
   then sends the same graceful RPC, never the lifecycle's kill-after-10-s fallback, and
   exits.
9. **Report** on the next tray start: `read_handoff_result` compares the version now
   running with the target. The exit code alone is not evidence, which is the lesson of
   `run_upgrade_checked`. The result is shown once: "Updated 2.43.2 → 2.44.0", or the
   reason (UAC declined, cancelled, hash mismatch, YazSes did not exit in time, an exit
   code), with the log path and `RELEASES_URL`.

Any failure before the hand-off leaves YazSes running and deletes any download and the
lock. Nothing is half-installed. Inno's own transaction covers a failure during the copy;
with a file still in use, `/SUPPRESSMSGBOXES` answers Abort and Inno rolls back. A failure
after the hand-off still ends with YazSes relaunched on whichever version is on disk.

The installer contract is pinned by `tests/test_one_click_windows_update.py`: the stable
AppId, `PrivilegesRequired=lowest`, `CloseApplications=yes` (now explicit, with `.pyd`
added to `CloseApplicationsFilter`), and `skipifsilent` on the `[Run]` launcher, so a
silent upgrade does not start a second tray.

### What is deliberately not done

- **No background download or install.** The optional `[general] update_check` watcher is
  unchanged. It only notifies. Every download in this ADR follows a confirmation.
- **No elevated run of a downloaded file.** See *Trust model*.
- **macOS `.app`** and **MSIX** are unchanged: download page and Store steps respectively.
- **No config key.** This is the existing Install action becoming able to act. It is not a
  new background capability, so AGENTS.md rule 2 (ship dormant) has nothing to switch off.
- **winget is not detectable.** A winget install runs the same Inno installer into the same
  directory as a direct download, and nothing on disk tells them apart, so
  `detect_install_method` classes it `windows-installer`. That was already true before this
  ADR. The `winget` branch of the one-click path is correct but unreachable until detection
  can tell, and the per-user installer path updates such an install anyway.

## Trust model

The Windows installer is **not code-signed yet**. The SignPath steps in
`build-windows.yml` are gated on secrets that have never been set.

- The SHA-256 from the **same** release's `SHA256SUMS.txt` gives **integrity**. The file is
  the one that release published and it arrived intact: no truncation, no corruption, no
  swap by a CDN or proxy, since TLS plus the hash covers the path.
- It does **not** give **authenticity**. An attacker who can replace a release asset can
  replace `SHA256SUMS.txt` too. That is the same trust a user places in the releases page
  when they download by hand, so the one-click path does not lower the bar. It also does
  not raise it.
- **Remaining step:** Authenticode signing. Once releases are signed, the job should
  require a valid signature from the expected publisher (`Get-AuthenticodeSignature`)
  before running, and refuse otherwise. Until then SmartScreen may still warn when the
  unsigned installer runs, and the docs say so.

**Elevation, and why all-users installs are excluded.** The download sits in the user's
`%TEMP%`. Another account cannot write there, but any process running as the same user
can. For a **per-user** install the installer runs unelevated, as that same user. A
same-user process that swaps the file between the final hash check and `Start-Process`
gains nothing it did not already have: it could modify the per-user install directly. The
re-check shrinks that window to milliseconds anyway.

For an **all-users** install it is different, and the first version of this ADR was wrong
to call it "not a new boundary". Inno would re-launch the file in `%TEMP%` with
administrator rights. A same-user, unelevated process that won the swap race would get its
own binary run elevated. That is a privilege escalation the one-click path would have
created. The alternative was to copy the verified file into a fresh Administrators-only
directory from an elevated helper and re-hash it there. That is the right design, but it
needs a second elevated script, ACL handling and Windows-only verification that this change
cannot test. So the robust part is the refusal: `one_click_offer` declines `"machine"` and
`"unknown"` scopes, and `build_handoff` / `build_script` both refuse an elevated
`installer` hand-off outright. The admin-only-copy design is the recorded next step if
all-users one-click is wanted.

**Chocolatey** is the one elevated run, and it does not run anything from `%TEMP%`. It runs
`choco.exe` by absolute path from Chocolatey's install directory, resolved from HKLM (which
only administrators can write), with fixed arguments. Chocolatey then fetches and verifies
its own package. That is the same as the user typing `choco upgrade yazses -y` in an
administrator shell. One residual: the unelevated PowerShell job that builds the elevated
command line is itself a same-user process, and could in principle be tampered with by
another same-user process before the UAC prompt. The UAC prompt shows the program being
elevated. Microsoft's security servicing criteria list UAC as a defense-in-depth feature,
not a security boundary, and bypasses are not serviced by default
([MSRC](https://www.microsoft.com/en-us/msrc/windows-security-servicing-criteria)). This
ADR does not claim more protection than that.

## Egress classification (ADR-019)

- `system/installer_update.py` is a **FETCH**. It reads the release JSON, `SHA256SUMS.txt`
  and the installer from `github.com` release assets. Nothing about the user is sent: no
  identifier, no config, no dictation. Like `system/deps.py`, what it fetches is **code
  that then runs**, and the inventory says so.
- `platform/windows/update_handoff.py` is a **SHELL_OUT**. It asks choco, winget or Scoop
  what their feed carries, then runs that manager's upgrade, which is already declared under
  `system/updater.py`. It sends the package name and nothing else.

## Consequences

- Windows users get the Ubuntu experience: one click, one confirmation, and YazSes comes
  back updated, for per-user installs and package managers whose feed has caught up.
- All-users installs keep the manual path until the admin-only-copy design is built.
- A second network request per update. The hand-off re-reads the release JSON because it
  needs the asset list, not just the version.
- The flow depends on Windows PowerShell 5.1, present on every supported Windows 10/11. If
  it is missing, the hand-off raises `OSError` and the user gets the manual steps.
- **Verification is partly automated.** The `windows-update-handoff` job in `test.yml`
  (advisory until it has passed on three consecutive pushes to `main`) runs
  `scripts/check_windows_update_handoff.py` on `windows-latest`. It drives the real
  `start_one_click_update` and `WindowsUpdateLauncher`, including the real HKCU uninstall-key
  read, `subprocess.Popen` and `powershell.exe -EncodedCommand` job. The release is a fake
  on 127.0.0.1 that answers 415 to the wrong `Accept`, and the installer is a compiled
  stand-in that records its arguments. It checks the wait, the re-hash, the in-place
  switches, the recorded exit code and the relaunch for a good, a failing, a tampered and
  a stuck update, in awkward paths (checklist items 4, 7 and 10 in miniature). It does not
  cover the real Inno installer, UAC, SmartScreen, DNS/TLS, GitHub's redirects, or a real
  tray and daemon. The checklist below is still the definition of done for the first
  Windows release that carries this.
- **Settings window: implemented** in `settingsui/maintenance_panel.py` (check off-thread,
  `confirmation_prompt`, `hand_off_outside_tray`, `QApplication.quit`); not yet verified on
  Windows. It waits on `os.getpid()` among the hand-off's PIDs (the default), and when
  one-click is refused it shows the same reason and manual steps as the tray.

## Revision (2026-10-20, after review)

A peer review, confirmed with `curl`, found the API `Accept` header bug (HTTP 415: the
feature could never have worked), the all-users elevation race, package feeds lagging the
tag, a force-close that could lose a meeting, MSIX misdetected as the `.exe` install, and
two clicks sharing one `.part` file. All are fixed as described above, each with tests.

## Windows verification checklist

1. Per-user `.exe` install of the previous release. Tray → *Check for updates…* → Yes →
   balloons for download and install → tray icon disappears → within about a minute
   YazSes starts again → balloon "YazSes updated X → Y". `yazses --version` reports Y.
   `%TEMP%\yazses-update\update.log` and `installer.log` exist; the `.exe` and
   `update.lock` are gone.
2. The same from a terminal: `yazses update --yes`, once with the tray quit first and once
   with it running. With it running, the CLI prints "Waiting for the YazSes tray to
   close…", the tray icon disappears within a few seconds, the daemon stops, the installer
   runs, and the tray comes back on Y.
3. Decline at the Yes/No box: nothing is downloaded.
4. Tamper test: edit a byte of the downloaded file during the shutdown window. The log
   says `SHA-256 mismatch`, nothing is installed, and YazSes relaunches on X.
5. Unplug the network after confirming: a clear balloon, the releases page opens, and
   YazSes keeps running.
6. All-users install (`/ALLUSERS`): no one-click is offered. The reason names all users,
   and the releases page opens.
7. Start a meeting, then update from the tray. The daemon is not force-closed: either it
   exits after saving and the update proceeds, or after 300 s nothing is installed and the
   next start says why.
8. Click *Check for updates…* twice quickly: the second attempt says an update is already
   in progress.
9. ARM64 machine: the x64 installer is chosen, installs and runs.
10. A user name with a space, an apostrophe and a non-ASCII letter: paths survive.
11. Chocolatey: the version is read from `choco search`, a lagging package is not offered,
    the UAC prompt names Chocolatey, and `choco.exe` runs from `C:\ProgramData\chocolatey`.
    Scoop: the `scoop info` output format matches the parser, and YazSes relaunches from
    `apps\yazses\current\`. winget: confirm it is still detected as `windows-installer`.
12. MSIX package: `yazses update --check` reports `via msix` with Store steps; the tray
    does not open the `.exe` page.
13. SmartScreen: note whether the unsigned installer is blocked when it runs silently.
