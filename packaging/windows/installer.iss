; Inno Setup script for YazSes (Windows).
;
; Wraps the PyInstaller --onedir bundle at dist/YazSes/ into a single
; self-contained installer at dist/YazSes-<version>-windows-x64.exe.
;
; Notable design choices:
;   - PrivilegesRequired=lowest: HKCU install, no UAC prompt for normal users.
;   - DefaultDirName under {userpf} so the installer can write without admin.
;     ({userpf} is %LOCALAPPDATA%\Programs, not %USERPROFILE% — the docs said
;     the latter for a long time and sent people to a folder that never exists.)
;   - Tray-app launcher is the default Start Menu entry; daemon is launched
;     by the tray on first run, not directly by the user.
;   - Optional autostart task uses Inno Setup's built-in `tasks` mechanism;
;     selecting it adds an HKCU\Run entry. Same key the WindowsLifecycle
;     class manages, so installer + in-app autostart toggle stay in sync.

#define MyAppName "YazSes"
#define MyAppVersion GetEnv('YAZSES_VERSION')
#if MyAppVersion == ""
  #define MyAppVersion "0.0.0"
#endif
; Target architecture, supplied by scripts/build-windows.ps1 from the build host
; (PyInstaller produces a native binary, so the host arch IS the target arch).
; Defaults to x64 so a hand-run ISCC still behaves as it always did.
#define MyAppArch GetEnv('YAZSES_ARCH')
#if MyAppArch == ""
  #define MyAppArch "x64"
#endif
#define MyAppPublisher "MSKazemi"
#define MyAppURL "https://github.com/MSKazemi/yazses"
; The windowed binary. Deliberately NOT "YazSes.exe": PATHEXT resolves .EXE
; before .CMD and NTFS is case-insensitive, so a YazSes.exe in {app} answers to
; a bare `yazses` and permanently shadows the yazses.cmd console shim below.
#define MyAppExeName "YazSesApp.exe"

[Setup]
AppId={{F3E8B8A4-1B6C-4F24-9BE8-9B7E58E9C4A2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={userpf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; An arm64 build must refuse to install on x64: the PyInstaller payload is native
; ARM64 and would not run there. x64compatible deliberately DOES include arm64
; (Windows runs x64 under emulation), so the x64 installer stays usable on an ARM
; machine as the slower fallback — but a native arm64 installer, when one exists,
; is the better answer and this is what lets both be published side by side.
#if MyAppArch == "arm64"
ArchitecturesAllowed=arm64
ArchitecturesInstallIn64BitMode=arm64
#else
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif
OutputDir=..\..\dist
OutputBaseFilename=YazSes-{#MyAppVersion}-windows-{#MyAppArch}
SolidCompression=yes
WizardStyle=modern
Compression=lzma
; The installer's own icon: the wizard window, its taskbar button, and the
; downloaded file in Explorer. Without it a first-time user downloads an unsigned
; .exe with a generic icon, which is the worst possible first impression.
; Path is relative to this .iss file.
SetupIconFile=..\..\assets\yazses.ico
; Stays pointed at the exe rather than at a copy of the .ico: the exe now carries
; the right icon resource, so Add/Remove Programs is correct for free and there is
; no second path to drift.
UninstallDisplayIcon={app}\{#MyAppExeName}
; In-place upgrade, including the one-click update from the tray / `yazses update`
; (ADR-027). The AppId above must never change: it is what makes a new installer
; upgrade this install (same directory, same install mode — UsePreviousAppDir and
; UsePreviousPrivileges both default to yes) instead of installing a second copy.
; CloseApplications is Inno's default; it is spelled out because the one-click update
; depends on it: run silently, Setup closes anything still holding a file it must
; replace through the Restart Manager. The filter adds .pyd — the bundle's Python
; extension modules are held open by a running YazSes exactly like its .dll files.
; The relaunch after a silent upgrade belongs to the update job (it starts YazSes
; again whether or not the upgrade worked), which is why the [Run] entry below keeps
; skipifsilent: a second launcher here would start two trays.
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd,*.chm
; We append {app} to the per-user PATH so `yazses doctor` works from a shell;
; this broadcasts WM_SETTINGCHANGE so open shells pick it up.
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "Start YazSes automatically when I sign in"; GroupDescription: "Optional:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Optional:"; Flags: unchecked

[InstallDelete]
; Upgrading from <= 2.18.2, where the windowed binary was named YazSes.exe.
; Inno only overwrites files it ships; an orphaned YazSes.exe left in {app}
; would keep answering to a bare `yazses` (PATHEXT puts .EXE ahead of .CMD) and
; the shim would stay shadowed even after this fix. Delete it explicitly.
Type: files; Name: "{app}\YazSes.exe"

[Files]
Source: "..\..\dist\YazSes\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; `yazses` on PATH → yazses-cli.exe (see yazses.cmd for why the rename).
Source: "yazses.cmd"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; No IconFilename: here on purpose. Every shortcut points at {#MyAppExeName},
; which carries the brand icon as a resource (packaging/windows/yazses.spec), so
; they all inherit it. Naming a .ico explicitly would add a fourth place the icon
; can go stale and would need the file shipped into {app}.
Name: "{group}\{#MyAppName}";        Filename: "{app}\{#MyAppExeName}"; Parameters: "--tray"
; A clickable Start-menu launcher for the settings window (#63) — the tray
; entry alone is not discoverable to someone who has not found the tray yet.
Name: "{group}\{#MyAppName} Settings"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--settings"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"; Parameters: "--tray"; Tasks: desktopicon

[Registry]
; HKCU\Run autostart entry, gated on the optional task. The in-app
; lifecycle.uninstall_autostart() removes the same key. Keep this byte-identical
; to WindowsLifecycle.resolve_tray_command(frozen=True) or the two drift apart.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "YazSes"; \
    ValueData: """{app}\{#MyAppExeName}"" --tray"; \
    Flags: uninsdeletevalue; Tasks: autostart

; Append {app} to the per-user PATH, but only when it isn't already there —
; NeedsAddPath guards against a repeat install stacking duplicate segments.
; Deliberately NOT uninsdeletevalue: that flag would delete the user's entire
; Path. Removal is surgical, in CurUninstallStepChanged below.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--tray"; \
    Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Best-effort: stop a running daemon before files vanish. The daemon's
; named-pipe IPC accepts `shutdown`; if not reachable, exit code is ignored.
Filename: "{app}\yazses-cli.exe"; Parameters: "stop"; Flags: runhidden; \
    RunOnceId: "stop-daemon"

[UninstallDelete]
; Add-on packs (ADR-028, owner answer to question 4): code only this app can load,
; installed per user under %LOCALAPPDATA%\yazses\packs (Paths.data_dir / "packs").
; Only the packs folder: config, logs and downloaded models beside it keep their
; current policy and are left alone.
;
; PER-USER INSTALLS ONLY. In an all-users (administrative install mode) uninstall,
; {localappdata} is the ELEVATED ADMINISTRATOR's profile, not the profile of whoever
; installed the packs, so this entry would delete the wrong account's folder and none
; of the users'. Inno's guidance for that mode is that user-level files are the app's
; job; `yazses doctor` and docs/windows-install.md name `yazses packs remove --all`.
; The Check gives the same answer whether Inno evaluates it when it writes the
; uninstall log or when it uninstalls: the install mode is fixed for one registration.
;
; Never on an upgrade: Inno runs [UninstallDelete] only from the uninstaller, and an
; in-place upgrade (including ADR-027's one-click update) never runs the uninstaller.
; Nothing in [Code] below deletes packs or starts the uninstaller either.
Type: filesandordirs; Name: "{localappdata}\yazses\packs"; Check: IsPerUserInstall

[Code]
{ ---- Install mode ------------------------------------------------------------

  The one gate on deleting per-user data at uninstall (see [UninstallDelete]). }

function IsPerUserInstall: Boolean;
begin
  Result := not IsAdminInstallMode;
end;

{ ---- PATH maintenance -------------------------------------------------------

  Touching PATH is the one thing here that can damage a machine beyond this
  app, so both directions are conservative: append only when absent, and on
  uninstall remove only our own exact segment, leaving the value untouched if
  anything is unexpected. }

function PathSegments(const Path: string): string;
begin
  { Pad so a segment match can be anchored on both sides and ';app' cannot
    match a longer '...;appdata' by prefix. }
  Result := ';' + Uppercase(Path) + ';';
end;

function NeedsAddPath(const Dir: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(PathSegments(Dir), PathSegments(OrigPath)) = 0;
end;

procedure RemovePath(const Dir: string);
var
  OrigPath: string;
  Needle: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
    exit;

  Needle := PathSegments(Dir);
  P := Pos(Needle, PathSegments(OrigPath));
  if P = 0 then
    exit;  { not ours to remove }

  { P indexes the padded string, whose leading ';' means P-1 indexes OrigPath.
    Cut our directory plus exactly one adjoining separator: the preceding one
    when we are not first, the following one when we are. Length(Needle)-1 is
    Length(Dir)+1 — Delete clamps if we were the only entry. }
  if P = 1 then
    Delete(OrigPath, 1, Length(Needle) - 1)          { 'DIR;rest' -> 'rest' }
  else
    Delete(OrigPath, P - 1, Length(Needle) - 1);     { 'head;DIR' -> 'head'  }

  RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemovePath(ExpandConstant('{app}'));
end;

{ ---- Closing a running YazSes before its files are replaced ------------------

  CloseApplications hands this to the Restart Manager, and the Restart Manager
  cannot do it: YazSes is a tray process plus a windowless `--daemon` child, so
  neither has a main window to ask, and Setup stops with "unable to automatically
  close all applications" (silent: exit code 5, nothing installed). That is every
  upgrade that starts while YazSes is running, other than the in-app one-click
  update, which waits for YazSes to exit before it starts this installer.

  So close it here, before Setup looks. Order matters. The tray goes first, and
  forcibly: it holds no user data, and while it lives it relaunches the daemon
  whenever the daemon disappears. Then `yazses-cli stop`, which asks the daemon
  to shut down and waits for it, so a meeting being saved is saved, not killed.
  Whatever survives that is left to the Restart Manager, which can still refuse:
  a daemon that will not stop is a reason not to install, not to kill it.

  Only processes running from this install's own directory are touched. }

var
  TrayWasRunning: Boolean;

function PsQuote(const S: string): string;
var
  T: string;
begin
  T := S;
  StringChangeEx(T, '''', '''''', True);
  Result := '''' + T + '''';
end;

function StopRunningYazSes: Boolean;
var
  AppDir, Script: string;
  ResultCode: Integer;
begin
  Result := False;
  AppDir := ExpandConstant('{app}');
  if not FileExists(AppDir + '\{#MyAppExeName}') then
    exit;  { first install: nothing of ours can be running }

  { Exit code 1 = a tray was found (and stopped), 0 = none. No double quotes in the
    script: it travels inside one -Command "..." argument. }
  Script :=
    '$d = ' + PsQuote(AppDir + '\') + '; ' +
    '$t = @(Get-CimInstance Win32_Process | Where-Object { ' +
      '$_.Name -eq ''{#MyAppExeName}'' -and $_.ExecutablePath -and ' +
      '$_.ExecutablePath.StartsWith($d, [StringComparison]::OrdinalIgnoreCase) -and ' +
      '$_.CommandLine -match ''--tray'' }); ' +
    '$t | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; ' +
    'exit [int]($t.Count -gt 0)';
  if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
          '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -Command "' +
          Script + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := ResultCode = 1;

  if FileExists(AppDir + '\yazses-cli.exe') then
    Exec(AppDir + '\yazses-cli.exe', 'stop', AppDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  TrayWasRunning := StopRunningYazSes;
  Result := '';  { never blocks the install: the Restart Manager is still the backstop }
end;

function RestartApplicationsRefused: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/NORESTARTAPPLICATIONS') = 0 then
      Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  { A silent upgrade (winget, choco, scoop, a script) has no "Launch YazSes now" box
    ([Run] is skipifsilent), so a tray we closed would stay closed. The in-app update
    passes /NORESTARTAPPLICATIONS and starts YazSes itself, so it is left alone. An
    interactive install keeps its finish-page checkbox. }
  if (CurStep = ssDone) and TrayWasRunning and WizardSilent
     and not RestartApplicationsRefused then
    ExecAsOriginalUser(ExpandConstant('{app}\{#MyAppExeName}'), '--tray',
                       ExpandConstant('{app}'), SW_SHOWNORMAL, ewNoWait, ResultCode);
end;
