#define MyAppName "MIDAS FLOOR LOAD TOOL"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "MIDAS FLOOR LOAD TOOL"
#define MyAppExeName "midas_floorload_auto_v4.exe"

[Setup]
AppId={{B4E2F45A-7B50-4F56-90A0-000000000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\MIDAS_FLOOR_LOAD_TOOL
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=MIDAS_FLOOR_LOAD_TOOL_Setup_{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
#ifexist "..\resources\app.ico"
SetupIconFile=..\resources\app.ico
#endif

[Files]
Source: "..\dist\midas_floorload_auto_v4\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "바탕화면 바로가기 만들기"; GroupDescription: "추가 아이콘:"; Flags: unchecked

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "프로그램 실행"; Flags: nowait postinstall skipifsilent
