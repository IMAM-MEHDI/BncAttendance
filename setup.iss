; Inno Setup Script for BNC Attendance System
; Generated for BNC Attendance EMS v1.1.0

[Setup]
AppId={{BNC-ATTENDANCE-EMS-2026}}
AppName=BNC Attendance EMS
AppVersion=1.1.0
AppPublisher=BNC Education
DefaultDirName={autopf}\BNC Attendance EMS
DefaultGroupName=BNC Attendance EMS
AllowNoIcons=yes
OutputDir=.
OutputBaseFilename=BNC_Attendance_Setup
SetupIconFile=desktop_app\assets\logo.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\BNC_Attendance_EMS.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: ".env"; DestDir: "{app}"; Flags: ignoreversion
; Include any extra DLLs if needed, but PyInstaller --onefile handles most
Source: "desktop_app\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\BNC Attendance EMS"; Filename: "{app}\BNC_Attendance_EMS.exe"
Name: "{autodesktop}\BNC Attendance EMS"; Filename: "{app}\BNC_Attendance_EMS.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BNC_Attendance_EMS.exe"; Description: "{cm:LaunchProgram,BNC Attendance EMS}"; Flags: nowait postinstall skipifsilent
