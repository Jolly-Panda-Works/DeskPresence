; DeskPresence installer (Inno Setup 6).
; The version is passed in at build time: ISCC /DMyAppVersion=1.2.37 installer.iss
; (tools/set_version.py decides it, so the installer matches the app and the release name).
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-unversioned"
#endif
; Windows file versions are numbers only: 1.8.0-dev.33 -> 1.8.0 for VersionInfoVersion
#define DashPos Pos("-", MyAppVersion)
#if DashPos > 0
  #define MyFileVersion Copy(MyAppVersion, 1, DashPos - 1)
#else
  #define MyFileVersion MyAppVersion
#endif
#define MyAppName "DeskPresence"
#define MyAppExe "DeskPresence.exe"

; Settings in %APPDATA%\DeskPresence are kept on uninstall, so a reinstall keeps your calibration.

[Setup]
; Fixed AppId: a newer installer upgrades the installed app instead of installing a second copy.
AppId={{5B0E7C2A-3F4D-4E8B-9C61-2D7A9E1F4B83}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Usef Farahmand
AppPublisherURL=https://www.useffarahmand.com/
AppSupportURL=https://github.com/Jolly-Panda-Works/DeskPresence/issues
AppUpdatesURL=https://github.com/Jolly-Panda-Works/DeskPresence/releases
AppCopyright=Copyright (c) 2026 Usef Farahmand
VersionInfoVersion={#MyFileVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; ask where to install
DisableDirPage=no
DisableProgramGroupPage=yes
; per-user install by default (no admin needed); the dialog lets you install for all users instead
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=DeskPresence_Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
LicenseFile=LICENSE
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
ShowLanguageDialog=auto
; close a running DeskPresence before upgrading / uninstalling (the app holds this mutex)
AppMutex=DeskPresence
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
#ifexist "Farsi.isl"
Name: "fa"; MessagesFile: "Farsi.isl"
#endif

[CustomMessages]
en.StartWithWindows=Start DeskPresence when I sign in to Windows
fa.StartWithWindows=اجرای DeskPresence هنگام ورود به ویندوز
en.Launch=Launch DeskPresence
fa.Launch=اجرای DeskPresence
en.Shortcuts=Shortcuts:
fa.Shortcuts=میانبرها:
en.Startup=Startup:
fa.Startup=شروع خودکار:

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:Shortcuts}"
Name: "autostart"; Description: "{cm:StartWithWindows}"; GroupDescription: "{cm:Startup}"

[Files]
Source: "dist\DeskPresence\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; same value the app's own "Start with Windows" switch uses, so both stay in sync
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "DeskPresence"; ValueData: """{app}\{#MyAppExe}"""; Tasks: autostart; Flags: uninsdeletevalue
; unticking the task on an upgrade removes an earlier autostart entry
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "DeskPresence"; Flags: deletevalue; Tasks: not autostart

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:Launch}"; Flags: nowait postinstall skipifsilent
