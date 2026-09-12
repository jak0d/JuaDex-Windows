; Inno Setup script for PDF Batch Separator
;
; Build the application first:
;     pyinstaller packaging/app.spec --noconfirm --clean
; then compile this script:
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
;
; The result is installer_output\PDF-Batch-Separator-<version>-Setup.exe

#define MyAppName "PDF Batch Separator"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "PDF Batch Separator contributors"
#define MyAppExeName "PDF Batch Separator.exe"
#define MyAppId "{{B4E8A0F3-9C2D-4E77-9B1A-5F3D7C6E8A21}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
InfoAfterFile=..\PRIVACY.md
OutputDir=..\installer_output
OutputBaseFilename=PDF-Batch-Separator-{#MyAppVersion}-Setup
SetupIconFile=..\src\pdf_batch_separator\resources\app.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; 64-bit only, as required by the product definition.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

; Install per-machine when elevated, otherwise per-user.  A standard user can
; install into their own profile and run the app without administrator rights.
PrivilegesRequiredOverridesAllowed=dialog
PrivilegesRequired=lowest

UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
AppUpdatesURL=
AppSupportURL=

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole PyInstaller one-folder build.  Python and every native dependency
; are included, so nothing else has to be installed on the target machine.
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\PRIVACY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Privacy statement"; Filename: "{app}\PRIVACY.md"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove only our own log folder; user documents are never touched.
Type: filesandordirs; Name: "{localappdata}\{#MyAppName}\logs"

[Registry]
; Optional: offer the app in the "Open with" list for PDFs without
; taking over the default association.
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; \
    ValueType: string; ValueName: ""; \
    ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
