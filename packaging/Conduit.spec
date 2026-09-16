# -*- mode: python ; coding: utf-8 -*-
import os
import re

ROOT = os.path.dirname(SPECPATH)


def _versao():
    """Le __version__ do pacote. O CI incrementa esse numero antes de chamar aqui, e a
    versao gravada no .exe tem que ser a mesma que a janela Sobre mostra."""
    fonte = open(os.path.join(ROOT, "conduit", "__init__.py"), encoding="utf-8").read()
    achado = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', fonte)
    return tuple(int(n) for n in achado.groups()) + (0,) if achado else (0, 0, 0, 0)


VERSAO = _versao()
VERSAO_TEXTO = "%d.%d.%d" % VERSAO[:3]

# Bloco de versao do Windows. Sem ele o .exe aparece sem Produto, sem Versao e sem
# empresa em Propriedades, Detalhes, e o SmartScreen trata isso como sinal ruim.
VERSION_FILE = os.path.join(SPECPATH, "version_info.txt")
with open(VERSION_FILE, "w", encoding="utf-8") as saida:
    saida.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={VERSAO}, prodvers={VERSAO},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable("040904B0", [
        StringStruct("CompanyName", "Vinicius Botelho"),
        StringStruct("FileDescription", "Conduit, cliente de API local"),
        StringStruct("FileVersion", "{VERSAO_TEXTO}"),
        StringStruct("InternalName", "Conduit"),
        StringStruct("LegalCopyright", "Vinicius Botelho. Licenca MIT."),
        StringStruct("OriginalFilename", "Conduit.exe"),
        StringStruct("ProductName", "Conduit"),
        StringStruct("ProductVersion", "{VERSAO_TEXTO}"),
      ])
    ]),
    VarFileInfo([VarStruct("Translation", [1033, 1200])])
  ]
)
""")

# O app e' Qt Widgets puro: desenha tudo com QPainter e fala rede com httpx. Sem
# podar, o PyInstaller carrega QML, Quick, PDF, OpenGL e o rasterizador de OpenGL
# por software (opengl32sw.dll, 20 MB sozinho): dezenas de megabytes que ninguem
# chega a abrir.
QT_SOBRANDO = (
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtQuick3D", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtMultimedia", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.Qt3DCore",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDBus", "PySide6.QtSvgWidgets",
    "PySide6.QtPrintSupport", "PySide6.QtHelp", "PySide6.QtDesigner",
)
BINARIOS_SOBRANDO = (
    "opengl32sw.dll", "qt6quick.dll", "qt6qml.dll", "qt6qmlmodels.dll",
    "qt6qmlworkerscript.dll", "qt6pdf.dll", "qt6opengl.dll",
    "qt6multimedia.dll", "qt6charts.dll", "qt6sql.dll", "qt6test.dll",
    "qt6designer.dll", "qt6help.dll", "qt6quick3d.dll",
)


def _descartar(item):
    """True para coisa que nao vai no pacote."""
    destino = item[0].replace("\\", "/").lower()
    nome = destino.rsplit("/", 1)[-1]
    if nome in BINARIOS_SOBRANDO:
        return True
    # Traducoes do proprio Qt: so' o portugues interessa.
    if "/translations/" in destino and destino.endswith(".qm"):
        return "_pt" not in nome
    return False


a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "CHANGELOG.md"), "."),
        (os.path.join(ROOT, "LICENSE"), "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # invoke entra como dependencia declarada do paramiko, mas o import la e opcional,
    # dentro de try, e so serve pro ProxyCommand do ssh_config, que este app nao usa.
    # Fora do pacote sao alguns megabytes a menos e nenhuma funcao a menos.
    excludes=["tkinter", "invoke", *QT_SOBRANDO],
    noarchive=False,
    optimize=0,
)
a.binaries = [b for b in a.binaries if not _descartar(b)]
a.datas = [d for d in a.datas if not _descartar(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Conduit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "assets", "conduit.ico"),
    version=VERSION_FILE,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Conduit",
)
