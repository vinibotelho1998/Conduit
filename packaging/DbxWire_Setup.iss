; Instalador do Dbx Wire.
;
; Compile por packaging/DbxWire.spec (PyInstaller) e depois este arquivo. A versao
; vem de /DMyAppVersion, passada pelo CI, com uma reserva pra compilar na mao.

#define MyAppName "Dbx Wire"
#ifndef MyAppVersion
  #define MyAppVersion "0.6.0"
#endif
#define MyAppPublisher "Dbx"
#define MyAppExeName "DbxWire.exe"
#define MyAppUrl "https://github.com/vinibotelho1998/dbx-wire"

[Setup]
; AppId fixo e unico: e' por ele que o Windows reconhece uma atualizacao no lugar
; de uma segunda instalacao. Nunca mudar entre versoes.
AppId={{91F27FF1-FD88-4E5C-B879-6D405CF30ABD}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}/issues
AppUpdatesURL={#MyAppUrl}/releases/latest
AppCopyright=Copyright (C) {#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoDescription=Instalador do {#MyAppName}
AppComments=Cliente de API local, sem conta e sem nuvem.
VersionInfoCompany={#MyAppPublisher}

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
LicenseFile=..\LICENSE

OutputDir=..\dist
OutputBaseFilename=DbxWire-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\dbxwire.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
SetupMutex=DbxWireSetupMutex

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\DbxWire\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir o {#MyAppName} agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal\__pycache__"

[Code]
; Dados ficam em %USERPROFILE%\Dbx-Wire, fora da pasta de instalacao, entao
; desinstalar nunca apaga workspace nem cofre de segredos sem perguntar.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dados: string;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  Dados := ExpandConstant('{%USERPROFILE}\Dbx-Wire');
  if not DirExists(Dados) then
    Exit;
  MsgBox('Os workspaces continuam em ' + Dados + #13#10 +
         'Apague essa pasta manualmente se nao quiser mais guardar nada.',
         mbInformation, MB_OK);
end;
