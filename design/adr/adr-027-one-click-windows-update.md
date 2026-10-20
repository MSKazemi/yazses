# ADR-027 — One-click update on Windows: verify, hand off, relaunch

**Status:** Accepted (2026-10-20)
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-019-egress-inventory-and-escalation]] (the egress row this adds),
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

A confirmed click, or `yazses update` with a yes, does all of this:

1. **Check:** as before, `updater.check_update` asks the GitHub release. The update must be
   strictly newer (`is_newer`). A draft or a prerelease is refused.
2. **Confirm:** a native Yes/No box (tray) or a prompt (CLI; `--yes` skips it). Only an
   explicit yes continues. If the box cannot be shown, the answer is no.
3. **Plan** (pure, `system/installer_update.py`). Pick `YazSes-<v>-windows-<arch>.exe` for
   the machine's native architecture (`IsWow64Process2`, then the environment). ARM64
   falls back to x64, which the `.iss` allows. x64 never takes arm64. The URL must parse as
   `https://github.com/MSKazemi/yazses/releases/download/<tag>/<that file>` on exactly
   `github.com`. A userinfo part, a port, a query, a `..` segment or an encoded slash is
   refused. The asset's SHA-256 comes from the release's `SHA256SUMS.txt`, and exactly one
   entry is required. If GitHub reports a `sha256:` digest for the asset, it must agree.
4. **Download** to `%TEMP%\yazses-update\` (per-user). The file is written to `.part` and
   renamed only after it verifies. Hard cap of 1 GiB, and never more than the size the
   release declares. Short reads are refused. 30 s read timeout, 30 min overall deadline.
   Redirects are followed only to https on `github.com` or `*.githubusercontent.com`.
5. **Verify before running.** The SHA-256 of the bytes written must match, or the file is
   deleted and the update refused.
6. **Hand off** (`platform/windows/update_handoff.py`, behind the new `UpdateLauncher`
   Protocol). A detached Windows PowerShell job is started by absolute path with
   `-EncodedCommand`. That avoids a `.ps1` file, the execution policy, cmd's `%`/`&`
   parsing and the OEM code page. The job:
   - waits for the tray, daemon and CLI PIDs to exit;
   - **re-checks the SHA-256** immediately before running;
   - runs `installer /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /CLOSEAPPLICATIONS
     /FORCECLOSEAPPLICATIONS /NORESTARTAPPLICATIONS /LOG=…`;
   - records the exit code and deletes the installer;
   - **starts YazSes again whether or not the update worked**.

   For choco, winget and Scoop the job runs `updater.upgrade_command(method)` with the
   flags an unattended run needs. Chocolatey runs elevated with `-Verb RunAs`. winget and
   Scoop output is captured to the log.
7. **Shut down:** after a successful hand-off, the tray quits and its `on_quit` sends the
   daemon `shutdown`. The CLI stops the daemon gracefully, so a meeting is finalised, then
   exits.
8. **Report** on the next tray start: `read_handoff_result` compares the version now
   running with the target. The exit code alone is not evidence, which is the lesson of
   `run_upgrade_checked`. The result is shown once: "Updated 2.43.2 → 2.44.0", or why not,
   with the log path and `RELEASES_URL`.

Any failure before the hand-off leaves YazSes running and deletes any download. The user
sees the reason and the existing manual steps, and the tray also opens the releases page.
Nothing is half-installed. Inno's own transaction covers a failure during the copy. A
failure after the hand-off still ends with YazSes relaunched on whichever version is on
disk.

The installer contract is pinned by `tests/test_one_click_windows_update.py`: the stable
AppId, `PrivilegesRequired=lowest`, `CloseApplications=yes` (now explicit, with `.pyd`
added to `CloseApplicationsFilter`), and `skipifsilent` on the `[Run]` launcher, so a
silent upgrade does not start a second tray.

### What is deliberately not done

- **No background download or install.** The optional `[general] update_check` watcher is
  unchanged. It only notifies. Every download in this ADR follows a confirmation.
- **macOS `.app`** is unchanged. It still opens the download page.
- **No config key.** This is the existing Install action becoming able to act. It is not a
  new background capability, so AGENTS.md rule 2 (ship dormant) has nothing to switch off.

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

UAC is handled as follows. A per-user install (`PrivilegesRequired=lowest`, the default)
needs no elevation. An install that was made "for all users" is upgraded in that mode
(`UsePreviousPrivileges`), so the installer raises its own UAC prompt. If the user
declines, the job records the failure and relaunches the old version. Chocolatey always
asks, because it writes to `ProgramData`. The confirmation text says both.

The staging directory is the user's `%TEMP%`. Another account cannot write to it. A process
running as the same user could still swap the file between the check and the run. The
re-check immediately before `Start-Process` shrinks that window to milliseconds. Such a
process could already modify a per-user install directly, so this is not a new boundary.

## Egress classification (ADR-019)

`system/installer_update.py` is a **FETCH**. It reads the release JSON, `SHA256SUMS.txt` and
the installer from `github.com` release assets. Nothing about the user is sent: no
identifier, no config, no dictation. Like `system/deps.py`, what it fetches is **code that
then runs**, and the inventory says so. The package-manager hand-off adds no new
destination. It runs the commands already declared in the `system/updater.py` shell-out
row, from a detached job that the import and argv scans cannot see, so ADR-019 records it
in prose.

## Consequences

- Windows users get the Ubuntu experience: one click, one confirmation, and YazSes comes
  back updated.
- A second network request per update. The hand-off re-reads the release JSON because it
  needs the asset list, not just the version.
- The flow depends on Windows PowerShell 5.1, present on every supported Windows 10/11. If
  it is missing, the hand-off raises `OSError` and the user gets the manual steps.
- **Verification is manual.** Nothing in CI runs the detached job on Windows. The checklist
  below is the definition of done for the first Windows release that carries this.

## Windows verification checklist

1. Per-user `.exe` install of the previous release. Tray → *Check for updates…* → Yes →
   balloons for download and install → tray icon disappears → within about a minute
   YazSes starts again → balloon "YazSes updated X → Y". `yazses --version` reports Y.
   `%TEMP%\yazses-update\update.log` and `installer.log` exist, and the `.exe` is gone.
2. The same from a terminal: `yazses update --yes`. The prompt returns, the daemon stops,
   the installer runs, and the tray comes back on Y.
3. Decline at the Yes/No box: nothing is downloaded.
4. Tamper test: edit a byte of the downloaded file during the shutdown window, or point
   the payload at a wrong hash in a dev build. The update is refused, the log says
   `SHA-256 mismatch`, and YazSes relaunches on X.
5. Unplug the network after confirming: a clear balloon, the releases page opens, and
   YazSes keeps running.
6. All-users install (`/ALLUSERS`): UAC appears. Accept → updated. Decline → relaunched on
   X with the "administrator permission" reason.
7. A meeting in progress during `yazses update --yes`: the recording is finalised, not
   lost.
8. ARM64 machine: the x64 installer is chosen, installs and runs.
9. A user name with a space, an apostrophe and a non-ASCII letter: paths survive.
10. Chocolatey (UAC prompt, `choco.log`), winget (captured output in `update.log`) and
    Scoop (relaunch from `apps\yazses\current\`).
11. SmartScreen: note whether the unsigned installer is blocked when it runs silently.
