# PyInstaller build. Run:  pyinstaller netpulse.spec
# Produces a single NetPulse executable with no Python install required.

block_cipher = None

a = Analysis(
    ["netpulse/app.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=["netpulse.cli"],
    excludes=[
        # PySide6 ships a lot that a diagnostics tool never touches.
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts",
        "tkinter", "matplotlib", "numpy",
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="NetPulse",
    console=False,
    upx=True,
    icon=None,
)
