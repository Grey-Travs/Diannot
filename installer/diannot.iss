; Inno Setup script for Diannot Studio — builds the friend-facing Windows installer.
;
; Prereqs:
;   1) (release) set DIANNOT_GEMINI_EMBED_KEY + run  uv run python scripts/make_release.py
;   2) build the app:  uv run pyinstaller diannot_studio.spec --noconfirm
; Compile this script with Inno Setup (free, https://jrsoftware.org/isdl.php):
;   ISCC installer\diannot.iss
; Output:  dist\installer\DiannotStudio-Setup.exe   (per-user install, no admin prompt)

#define AppName "Diannot Studio"
#define AppVersion "0.6.2"
#define AppExe "DiannotStudio.exe"
#define AppPublisher "Diannot"

[Setup]
; Resolve all relative paths (Source/SetupIconFile/OutputDir) from the REPO ROOT, not from
; this script's folder (installer\). Inno's SourceDir defaults to the .iss directory, so without
; this the dist\/assets\ paths below would wrongly point at installer\dist, installer\assets, etc.
SourceDir=..
; A fixed AppId keeps upgrades/uninstall clean across versions — do not change it.
AppId={{A7E4C1B2-9D3F-4E8A-B6C5-1F2D3A4B5C6D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
; Per-user install dir → no UAC/admin prompt (matches "download and run").
DefaultDirName={localappdata}\Programs\DiannotStudio
DefaultGroupName=Diannot Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist\installer
OutputBaseFilename=DiannotStudio-Setup
SetupIconFile=assets\diannot.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "dist\DiannotStudio\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Diannot Studio"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"
Name: "{group}\Uninstall Diannot Studio"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Diannot Studio"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch Diannot Studio now"; Flags: nowait postinstall skipifsilent
