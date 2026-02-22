; BurnBar Inno Setup installer script
; Build: iscc installer.iss

[Setup]
AppName=BurnBar
AppVersion=1.0
AppPublisher=apresence
DefaultDirName={localappdata}\BurnBar
DefaultGroupName=BurnBar
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=BurnBar-Setup
Compression=lzma2
SolidCompression=yes
UninstallDisplayName=BurnBar

[Files]
Source: "dist\BurnBar.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\BurnBar"; Filename: "{app}\BurnBar.exe"
Name: "{group}\Uninstall BurnBar"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\BurnBar.exe"; Description: "Launch BurnBar"; Flags: nowait postinstall skipifsilent
