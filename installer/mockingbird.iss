; Inno Setup 6 script. Built by installer/build.py, which passes AppVersion, Staging, OutDir
; and Repo; compiling it by hand needs the same /D defines.
;
; Per-user and without admin rights: the app writes its interviews, models and runtime beside
; itself, so it must live somewhere the user can write.

#ifndef AppVersion
  #error Build with installer/build.py, which defines AppVersion, Staging, OutDir and Repo
#endif

[Setup]
AppId={{6F0A3C1E-5B7D-4E2A-9C8F-1D4B6A2E7C90}
AppName=Mockingbird
AppVersion={#AppVersion}
AppVerName=Mockingbird {#AppVersion}
AppPublisher=Duy Nguyen
AppPublisherURL=https://github.com/zuychin03/mockingbird
; Product metadata in the file's properties; SignPath requires it before it will sign.
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Mockingbird
VersionInfoProductVersion={#AppVersion}
VersionInfoCompany=Duy Nguyen
VersionInfoDescription=Mockingbird installer
VersionInfoCopyright=Copyright (c) 2026 Duy Nguyen
DefaultDirName={localappdata}\Programs\Mockingbird
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile={#Repo}\LICENSE
InfoBeforeFile={#Repo}\installer\before-install.txt
OutputDir={#OutDir}
OutputBaseFilename=Mockingbird-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#Repo}\installer\mockingbird.ico
UninstallDisplayName=Mockingbird
UninstallDisplayIcon={app}\mockingbird.ico

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#Staging}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Repo}\installer\mockingbird.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Mockingbird"; Filename: "{app}\python\python.exe"; Parameters: "-m app.launch"; WorkingDir: "{app}"; IconFilename: "{app}\mockingbird.ico"; Comment: "Practise a software-engineering interview"
Name: "{autodesktop}\Mockingbird"; Filename: "{app}\python\python.exe"; Parameters: "-m app.launch"; WorkingDir: "{app}"; IconFilename: "{app}\mockingbird.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\python\python.exe"; Parameters: "-m app.launch"; WorkingDir: "{app}"; Description: "Start Mockingbird now (the first start asks what to download)"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; What first run downloaded or generated. data\, which holds the interviews, is left alone.
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\api"
; The cloud provider's API key, DPAPI-encrypted; an uninstall should not leave it behind.
Type: filesandordirs; Name: "{app}\secrets"
