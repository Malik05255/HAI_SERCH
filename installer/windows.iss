#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

[Setup]
AppId={{9AF05021-6D1B-4FF2-9D2A-70EF84106A9C}
AppName=البحث العميق
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\Deep Search
DefaultGroupName=البحث العميق
UsePreviousAppDir=yes
UsePreviousGroup=yes
DisableProgramGroupPage=auto
OutputDir=dist
OutputBaseFilename=deep-search-windows-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\deep_search.exe

[Files]
Source: "..\app\build\windows\x64\runner\Release\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\البحث العميق"; Filename: "{app}\deep_search.exe"
Name: "{autodesktop}\البحث العميق"; Filename: "{app}\deep_search.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "أيقونة سطح المكتب"; Flags: unchecked

[Run]
Filename: "{app}\deep_search.exe"; Description: "تشغيل البحث العميق"; Flags: nowait postinstall skipifsilent
