; Inno Setup script: turns the built app into one installer, DocToolkit-Setup-<version>.exe
;
; 1. Build the app first:   venv\Scripts\pyinstaller --noconfirm --clean DocToolkit.spec
; 2. Then build the installer (Inno Setup 6 must be installed):
;        & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;    The installer is saved in the "installer" folder.
;
; Keep AppVersion the same as __version__ in app\__init__.py.

#define AppName "DocToolkit"
#define AppVersion "1.0.0"
#define AppPublisher "Tariq Alanazi"
#define AppExe "DocToolkit.exe"

[Setup]
; AppId identifies DocToolkit to Windows. Never change it, or updates install side by side.
AppId={{9A4655C8-04ED-4B1E-B922-CBAAFABAB862}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Installs for the current user without asking for admin rights.
; People can still choose "install for all users" in the first screen.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=LICENSE
OutputDir=installer
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Close DocToolkit automatically if it is running during an update.
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Remove files left by an older version before copying the new ones.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\DocToolkit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
