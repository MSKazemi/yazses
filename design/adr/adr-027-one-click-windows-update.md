# ADR-027 — One-click update on Windows: verify, hand off, relaunch

**Status:** Accepted (2026-10-20; revised the same day after review, and on 2026-10-21 to
cover all-users installs, see *Revision*)
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
- **An install the uninstall key can place** for `windows-installer`.
  `WindowsUpdateLauncher.install_scope` matches the running directory against the Inno
  uninstall key (`{AppId}_is1`, `Inno Setup: App Path`) under HKCU and HKLM. A match under
  HKCU is `"user"`: the installer runs unelevated. A match under HKLM is `"machine"`
  (all users): offered since 2026-10-21 as `Offer(ok=True, all_users=True)`, and run
  through *The all-users path* below, with one UAC prompt. A machine can carry both keys
  (an old all-users install left behind); the running directory decides. A match under
  neither is `"unknown"` and is refused, because nothing says which privileges its
  upgrade needs.
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
   - for a **per-user** install, runs `installer /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
     /SP- /CLOSEAPPLICATIONS /NORESTARTAPPLICATIONS /LOG=…`, unelevated;
   - for an **all-users** install, elevates the job described in *The all-users path*
     instead. The downloaded file itself is never elevated;
   - records the exit code and deletes the installer and the lock;
   - **starts YazSes again whether or not the update worked**, unelevated, as the user. If
     an old process is still running, the second tray finds the single-instance lock held
     and exits quietly.

   For choco, winget and Scoop the job runs `updater.upgrade_command(method)` plus the
   flags an unattended run needs, by absolute path. winget and Scoop are resolved from
   `PATH` and run unelevated, with output captured to the log. **Chocolatey** runs
   elevated (`ProcessStartInfo` with `Verb = 'runas'`, so a declined prompt is recorded as
   such). Its `choco.exe` comes from the **machine** environment's `ChocolateyInstall`
   (HKLM) and nowhere else. Not from this process's environment: a user-level variable is
   writable by any same-user process. Since 2026-10-21, also not from the default
   `C:\ProgramData\chocolatey` when that variable is missing; see *Trust model*.
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
AppId, `PrivilegesRequired=lowest`, `PrivilegesRequiredOverridesAllowed` allowing the
command line (so `/ALLUSERS` is honoured), `CloseApplications=yes` (now explicit, with
`.pyd` added to `CloseApplicationsFilter`), and `skipifsilent` on the `[Run]` launcher, so a
silent upgrade does not start a second tray.

### The all-users path (2026-10-21)

An all-users install lives under `Program Files` and is upgraded only with administrator
rights. The first version refused it, because the obvious design (elevate the downloaded
`.exe`) would have run a file from the user-writable `%TEMP%` with administrator rights.
The rule this design follows is that **the elevated side trusts nothing a non-administrator
can write.**

1. The **unelevated** job does everything it does for a per-user install up to the run:
   waits for YazSes to exit and re-hashes the download. That re-hash is now only a
   courtesy, sparing a UAC prompt for a file that is already wrong.
2. It starts System32's Windows PowerShell, found through `[Environment]::SystemDirectory`
   rather than `$env:` or `PATH`, with `Verb = 'runas'`. That is **one UAC prompt**, and it
   names *Windows PowerShell*, publisher Microsoft Windows. The confirmation box and the
   CLI say so beforehand (`installer_update.ALL_USERS_NOTE`). The elevated command line is
   `-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden
   -EncodedCommand <payload>`. The payload is generated by
   `update_handoff.build_admin_install_script`, with every interpolated value passed
   through `ps_quote`. It carries the expected SHA-256 as a **literal**.
3. The **elevated** script:
   - sets `$PSModuleAutoLoadingPreference = 'None'` and uses only .NET types. No cmdlet can
     be auto-loaded from a module on the user's `PSModulePath`, and `-NoProfile` skips the
     user's profile script;
   - builds `<Windows>\Temp\yazses-update-<128-bit random>` from `GetSystemDirectory`, and
     refuses a name that already exists. `<Windows>\Temp` is used rather than
     `$env:ProgramData\YazSes`: a user can redefine `ProgramData` in their own environment,
     and `%ProgramData%` lets users create folders, so `ProgramData\YazSes` could already
     exist and be owned by them. As owner of the parent, they could then rename our
     directory out from under the job;
   - creates the directory **with** its security descriptor
     (`Directory.CreateDirectory(path, DirectorySecurity)`): owner BUILTIN\Administrators,
     inheritance disabled (`SetAccessRuleProtection($true, $false)`), and FullControl for
     `S-1-5-32-544` and `S-1-5-18` only, by SID because group names are localised. The ACL is
     therefore in place before anything is copied; there is never a moment with an
     inherited ACL. It then reads back the owner, the protection flag and that the
     directory is empty, and stops with exit `-5` if any of them is wrong;
   - copies the download in with `File.Copy`. The `%TEMP%` file is only ever *read*, once;
   - opens **the copy** deny-write (`FileShare.Read`), computes its SHA-256 and compares it
     with the literal. On a mismatch it exits `-2` and runs nothing. It keeps the handle
     open across the start of the installer, so no writer can exist between the hash and
     the run;
   - runs the copy with `UseShellExecute = $false`, the switches plus `/ALLUSERS`, the
     directory as working directory, and **`TEMP`/`TMP` set to the directory**. Inno
     extracts its `setup.tmp` to the temp path, which for a non-SYSTEM process is `TMP`,
     then `TEMP` (`GetTempPath2`). Left alone, that would be the user's `%TEMP%`, even
     elevated. There is no `/LOG`: an elevated write to a user-writable place is how a
     planted junction becomes "write any file", so the elevated side writes nothing there;
   - deletes the directory in a `finally` and `exit`s with the installer's code, or with
     `-5`, `-1` or `-2`. It never relaunches anything.
4. The unelevated job waits for that process, through the `Process` handle that
   `ShellExecuteEx` returns, and records its exit code. A declined prompt, `ShellExecuteEx`
   failing with `ERROR_CANCELLED` (1223), is recorded as **`-4`**. Then, as always, it
   deletes the download and the lock and relaunches YazSes, unelevated.
5. The next start explains `-4` ("administrator permission … was declined") and `-5` ("could
   not be copied into a folder only administrators can change") as well as the old codes.

The alternative was to keep the `%TEMP%` file open deny-write from the elevated side
across the hash and the launch, and run it in place. It was rejected because it is weaker
and harder to test:

- Process creation takes a **path**. With the parent directories left user-writable, the
  guarantee depends on NTFS refusing renames and junction swaps of ancestors while a file
  is open, which cannot be shown from Linux CI.
- Inno would still extract `setup.tmp` into the user's `%TEMP%`.
- A user-writable application directory is the classic DLL-planting position for an
  elevated installer.

The copy design depends only on a DACL access check. The generated text can be pinned in
unit tests, and real PowerShell can exercise it on the runner (*Consequences*).

### What is deliberately not done

- **No background download or install.** The optional `[general] update_check` watcher is
  unchanged. It only notifies. Every download in this ADR follows a confirmation.
- **No elevated run of a file in a user-writable place**, and no elevated write to one. See
  *The all-users path* and *Trust model*.
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

**Per-user installs.** The download sits in the user's `%TEMP%`. Another account cannot
write there, but any process running as the same user can. For a **per-user** install the
installer runs unelevated, as that same user. A same-user process that swaps the file
between the final hash check and `Start-Process` gains nothing it did not already have: it
could modify the per-user install directly. The re-check shrinks that window to
milliseconds anyway.

**All-users installs: what the admin-only copy protects, and what it does not.** The first
version of this ADR was wrong to call the all-users case "not a new boundary". Elevating
the `%TEMP%` file would let a same-user, unelevated process that wins the swap race between
the hash check and the start get *its* binary run with administrator rights. One-click
would have created that escalation. *The all-users path* closes it as follows.

- **Protected: the file that runs elevated is the file that was hashed.** The elevated
  process trusts no user-writable input. Its expected hash, source path and switches are
  part of its command line. The Application Information service creates the elevated
  process "with an administrative user's full access token"
  ([UAC architecture](https://learn.microsoft.com/windows-server/security/user-account-control/how-user-account-control-works#uac-architecture)).
  From then on, a non-elevated process cannot change it: "Applications with lower
  integrity levels can't modify data in applications with higher integrity levels"
  ([How UAC works](https://learn.microsoft.com/windows/security/application-security/application-control/user-account-control/how-it-works)),
  and every object is created with `NO_WRITE_UP` by default
  ([Mandatory Integrity Control](https://learn.microsoft.com/windows/win32/secauthz/mandatory-integrity-control)).
  The copy, the hash and the run all happen in a directory whose DACL names only
  Administrators and SYSTEM. Neither a different standard user nor the same user's own
  non-elevated processes can write there. For the latter, the reason is that the standard
  token has "the administrative Windows privileges and SIDs … removed" (same page).
  Microsoft relies on the same mechanism for its own elevated temp files: `GetTempPath2`
  returns `C:\Windows\SystemTemp` to SYSTEM because "that directory is ACL'd with the
  correct permissions to prevent common path redirection issues"
  ([GetTempPath2](https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-gettemppath2w)).
  The same mechanism keeps Inno's extracted `setup.tmp` out of the user's `%TEMP%`, and
  out of reach of DLL planting beside the installer.
- **Not protected: tampering before the UAC prompt.** The process that *asks* for elevation
  is the unelevated job, a same-user process. Another same-user process can rewrite its
  memory or its command line before consent, or define environment variables that the
  elevated PowerShell will inherit. The UAC prompt would still show "Windows PowerShell,
  Microsoft Windows". Microsoft says this plainly: "Same-desktop Elevation in UAC isn't a
  security boundary. It can be hijacked by unprivileged software that runs on the same
  desktop" ([Microsoft Learn](https://learn.microsoft.com/troubleshoot/windows-server/windows-security/disable-user-account-control#more-information)).
  The MSRC servicing criteria list UAC as defense-in-depth with no intent to service, and
  treat administrators as part of the TCB
  ([MSRC](https://www.microsoft.com/en-us/msrc/windows-security-servicing-criteria)).
  - What a code-signing certificate would add: a UAC prompt for the *installer* that names
    its publisher.
  - What this ADR claims: a same-user attacker who can already inject code into the
    user's processes can hijack this elevation as they can any other. That residual is
    the same for a user who downloads the installer and double-clicks it, which is the
    manual path. The manual path is in fact weaker on the axis this design closes: it
    elevates a file from a user-writable `Downloads` folder.
- **On "admin-only directories are a security boundary".** The MSRC criteria do not say
  that in those words. Its listed boundaries are the user, session, process, kernel and
  similar boundaries. What holds is narrower:
  - a non-administrator principal cannot write an object whose DACL grants it nothing;
  - writing one anyway is a privilege escalation across the **user boundary**, which MSRC
    does service;
  - for the *same* user's medium-integrity processes, the DACL check is what stops them.
    Microsoft does not promise to treat a bypass of that as a boundary violation, because
    same-desktop elevation is not one.

  This ADR relies on the access check, not on a servicing promise.
- **Not covered: a compromised administrator, or a compromised release.** Administrators
  are the TCB. A replaced release asset plus a replaced `SHA256SUMS.txt` still passes
  (see above: integrity, not authenticity).

**Chocolatey** does not run anything from `%TEMP%`. It runs `choco.exe` by absolute path
with fixed arguments. Chocolatey then fetches and verifies its own package, which is the
same as the user typing `choco upgrade yazses -y` in an administrator shell.

- **Where `choco.exe` comes from.** Its directory comes from HKLM's `ChocolateyInstall`,
  which only administrators can write. Chocolatey's setup writes that variable at machine
  scope for an administrator install (`Install-ChocolateyEnvironmentVariable … Machine`
  in `chocolateysetup.psm1`). Chocolatey also "only locks down the permissions to Admins
  when installed to the default location"
  ([Chocolatey setup](https://docs.chocolatey.org/en-us/choco/setup/)).
- **Hardened 2026-10-21: no default-directory fallback.** The 2026-10-20 code fell back to
  `C:\ProgramData\chocolatey` when that variable was missing. With no Chocolatey install
  there to lock it down, a user can create that folder under `%ProgramData%`, and YazSes
  would have elevated a planted `choco.exe`. `chocolatey_exe` now returns `None` when the
  variable is missing, and Chocolatey gets the manual steps.
- **Residual: pre-consent tampering.** This is the same class as for the installer path:
  the unelevated job is a same-user process and can be tampered with before the UAC
  prompt. The prompt names Chocolatey's signed `choco.exe`.
- **Not hardened: a non-default `ChocolateyInstall`.** A directory an administrator
  pointed there without restricting it is the administrator's configuration, and the
  Chocolatey docs say to restrict it.

This ADR does not claim more protection than the points above.

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
  back updated, for per-user installs, all-users installs (plus one UAC prompt), and
  package managers whose feed has caught up. Only an install whose scope the uninstall
  key cannot place, MSIX and macOS keep the manual path.
- An all-users update keeps no Inno log. `/LOG` would be an elevated write to a
  user-writable place, and the admin-only directory is deleted afterwards. `update.log`
  records the elevated job's exit code. To diagnose, run the installer by hand with
  `/LOG=`.
- **Unknown limit: the elevated command line.** The `-EncodedCommand` payload makes it
  about 5,000–6,000 characters. `CreateProcess` allows 32,767, and Microsoft documents
  no limit for `ShellExecuteEx`'s `lpParameters`. Old community reports describe failures
  near 2,048 characters on older shells. A failure there is safe: `ShellExecuteEx` errors,
  the code is `-1`, and YazSes relaunches. Checklist item 17 measures it on a real UAC
  prompt, and a unit test holds it under 8,000.
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
  a stuck update, in awkward paths (checklist items 4, 7 and 10 in miniature).

  It also runs the **all-users path** for real. GitHub's Windows runners "are configured to
  run as administrators with User Account Control (UAC) disabled"
  ([GitHub Docs](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)),
  so `runas` elevates without a prompt. The run uses:
  - a real HKLM uninstall key;
  - the real `ShellExecuteEx` start of System32's PowerShell with the real elevated
    payload;
  - a stand-in installer that records where it ran and the SDDL of its directory.

  Against those it checks `<Windows>\Temp\yazses-update-<random>`, TEMP/TMP/working
  directory there, owner `BA`, a protected DACL naming only `BA` and `SY`, `/ALLUSERS`
  and no `/LOG`, the directory deleted, and the relaunch. It then runs the elevated script
  directly with a matching and a wrong hash. The wrong hash must give exit -2, nothing
  run, and the source untouched.

  None of it covers the real Inno installer, the UAC *prompt* (consent, decline,
  over-the-shoulder credentials), a filtered admin token being denied the directory,
  SmartScreen, DNS/TLS, GitHub's redirects, or a real tray and daemon. The checklist below
  is still the definition of done for the first Windows release that carries this.
- **No Settings-window button yet.** The Settings window has no update entry. A button
  needs `settingsui/app.py`, which was out of scope for the 2026-10-21 change. It should
  check off the UI thread, ask with the same `confirmation_prompt`, call
  `hand_off_outside_tray` with `os.getpid()` among the waited PIDs (the default), and quit
  its own `QApplication` on success.

## Revision (2026-10-20, after review)

A peer review, confirmed with `curl`, found the API `Accept` header bug (HTTP 415: the
feature could never have worked), the all-users elevation race, package feeds lagging the
tag, a force-close that could lose a meeting, MSIX misdetected as the `.exe` install, and
two clicks sharing one `.part` file. All are fixed as described above, each with tests.

## Revision (2026-10-21, all-users installs)

All-users installs went from "refused, update by hand" to one-click with one UAC prompt,
through *The all-users path*.

- **Chosen design: admin-only copy.** It was chosen over holding the `%TEMP%` file open
  deny-write, because it rests on one DACL check rather than on NTFS rename semantics,
  and it can be pinned in text and run on the Windows runner.
- **Tests.** The generated scripts are pinned by unit tests:
  - the ACL is set at creation, before the copy;
  - the hash is the copy's, compared with a literal;
  - the installer starts from the admin-only directory while held open;
  - there is cleanup on every path and one `exit`;
  - there are no cmdlets, `$env:`, writes or relaunch on the elevated side;
  - hostile paths (apostrophe, backtick, `$(`, the four Unicode single quotes) appear only
    inside literals;
  - a declined UAC prompt is recorded as -4, and the relaunch still happens.
- **Checks outside the unit tests.** The real PowerShell 7.6 parser was run over the
  generated scripts. It parses all of them and tokenises every payload-bearing token as a
  single-quoted `StringLiteral`. A deliberately unsafe control script fails that check.
  The Windows CI job above now runs the path for real.
- **Chocolatey.** It lost its default-directory fallback, and its elevation now reports a
  declined prompt as -4.

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
6. All-users install (`/ALLUSERS`, as an administrator) of the previous release. Tray →
   *Check for updates…*.
   - The Yes/No box says Windows will ask for administrator permission and that the prompt
     names Windows PowerShell. Answer Yes.
   - Exactly one UAC prompt appears: *Windows PowerShell*, verified publisher *Microsoft
     Windows*. Answer Yes.
   - Note whether the prompt came to the front or waited as a flashing taskbar button. The
     request comes from a windowless background job, and this ADR found no Microsoft
     documentation either way. The Chocolatey path has the same property.
   - YazSes closes, updates and starts again. In Task Manager → Details → *Elevated*, the
     new tray shows **No**.
   - The balloon says "YazSes updated X → Y". HKLM
     `…\Uninstall\{F3E8B8A4-1B6C-4F24-9BE8-9B7E58E9C4A2}_is1` shows `DisplayVersion` Y, and
     the files in `C:\Program Files\YazSes` are new. No second, per-user copy appears under
     `%LOCALAPPDATA%\Programs`.
   - `%TEMP%\yazses-update\update.log` contains "asking Windows for administrator permission
     (all-users install)" and exit code 0. The `.exe` and `update.lock` are gone, and no
     `C:\Windows\Temp\yazses-update-*` directory is left.
7. Start a meeting, then update from the tray. The daemon is not force-closed: either it
   exits after saving and the update proceeds, or after 300 s nothing is installed and the
   next start says why.
8. Click *Check for updates…* twice quickly: the second attempt says an update is already
   in progress.
9. ARM64 machine: the x64 installer is chosen, installs and runs.
10. A user name with a space, an apostrophe and a non-ASCII letter: paths survive.
11. Chocolatey: the version is read from `choco search`, a lagging package is not offered,
    the UAC prompt names Chocolatey, and `choco.exe` runs from `C:\ProgramData\chocolatey`.
    Answering No at that prompt relaunches YazSes, and the next start says the permission
    was declined. With the machine-level `ChocolateyInstall` removed, no one-click is
    offered.
    Scoop: the `scoop info` output format matches the parser, and YazSes relaunches from
    `apps\yazses\current\`. winget: confirm it is still detected as `windows-installer`.
12. MSIX package: `yazses update --check` reports `via msix` with Store steps; the tray
    does not open the `.exe` page.
13. SmartScreen: note whether the unsigned installer is blocked when it runs silently.
    For the all-users path, the elevated copy runs with `UseShellExecute = $false`, so note
    whether SmartScreen intervenes at all there.
14. All-users, **decline**: repeat item 6 but answer No at the UAC prompt.
    - Nothing is installed, and YazSes starts again on X.
    - `update.log` says "administrator permission was declined at the UAC prompt", and
      `exit-code.txt` holds `-4`.
    - The next start says "Windows asked for administrator permission and it was
      declined".
    - No `C:\Windows\Temp\yazses-update-*` directory exists.
15. All-users, **standard user**: a non-administrator account using an all-users install.
    - The UAC prompt asks for an administrator's credentials (over-the-shoulder). Enter
      them, and the update installs.
    - YazSes starts again as the *standard* user.
    - Record whether Inno's per-user parts (the HKCU `Run` autostart and the `Path` entry)
      land in the administrator's hive instead. That is Inno's behaviour for any elevated
      run, not this ADR's.
16. All-users, **the directory really is admin-only**: in a second, non-elevated
    PowerShell, poll for `C:\Windows\Temp\yazses-update-*` while the installer runs (it
    takes a few seconds).
    - `icacls` on it shows owner `BUILTIN\Administrators`, no inherited entries, and only
      `BUILTIN\Administrators` and `NT AUTHORITY\SYSTEM`.
    - `New-Item -Path <dir>\x.txt` from the non-elevated shell fails with access denied.
    - Do the same with the account a standard user, if one is available.
17. All-users, **long command line**: a user whose profile path is long and non-ASCII.
    The UAC prompt still appears: `ShellExecuteEx` accepted the roughly 5–6 K character
    elevated command line on a real prompt. If it does not appear, the log names the
    `ShellExecuteEx` error, YazSes relaunches, and this is the open question in
    *Consequences*.
18. **Unknown scope**: copy the install directory to `D:\Portable\YazSes` and run it from
    there. No one-click is offered, the reason says "Could not tell", and the releases
    page opens.
