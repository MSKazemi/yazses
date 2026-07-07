; Inno Setup script for YazSes (Windows).
;
; Wraps the PyInstaller --onedir bundle at dist/YazSes/ into a single
; self-contained installer at dist/YazSes-<version>-windows-x64.exe.
;
; Notable design choices:
;   - PrivilegesRequired=lowest: HKCU install, no UAC prompt for normal users.
;   - DefaultDirName under {userpf} so the installer can write without admin.
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
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=YazSes-{#MyAppVersion}-windows-x64
SolidCompression=yes
WizardStyle=modern
Compression=lzma
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autostart"; Description: "Start YazSes automatically when I sign in"; GroupDescription: "Optional:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Optional:"; Flags: unchecked

[Files]
Source: "..\..\dist\YazSes\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}";        Filename: "{app}\{#MyAppExeName}"; Parameters: "--tray"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"; Parameters: "--tray"; Tasks: desktopicon

[Registry]
; HKCU\Run autostart entry, gated on the optional task. The in-app
; lifecycle.uninstall_autostart() removes the same key.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "YazSes"; \
    ValueData: """{app}\{#MyAppExeName}"" --tray"; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--tray"; \
    Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Best-effort: stop a running daemon before files vanish. The daemon's
; named-pipe IPC accepts `shutdown`; if not reachable, exit code is ignored.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--cli stop"; Flags: runhidden; \
    RunOnceId: "stop-daemon"
