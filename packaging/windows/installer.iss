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
#define MyAppExeName "YazSes.exe"

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
UninstallDisplayIcon={app}\{#MyAppExeName}
; We append {app} to the per-user PATH so `yazses doctor` works from a shell;
; this broadcasts WM_SETTINGCHANGE so open shells pick it up.
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "Start YazSes automatically when I sign in"; GroupDescription: "Optional:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Optional:"; Flags: unchecked

[Files]
Source: "..\..\dist\YazSes\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; `yazses` on PATH → yazses-cli.exe (see yazses.cmd for why the rename).
Source: "yazses.cmd"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}";        Filename: "{app}\{#MyAppExeName}"; Parameters: "--tray"
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

[Code]
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
