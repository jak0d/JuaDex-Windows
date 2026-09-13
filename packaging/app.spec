# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for PDF Batch Separator.

Produces a windowed (no console) 64-bit Windows application.  Build with:

    pyinstaller packaging/app.spec --noconfirm --clean

Two artefacts are produced under ``dist/``:

* ``PDF Batch Separator/``      - the one-folder build used by the installer
                                  and shipped as the portable ZIP.
* ``PDF Batch Separator.exe``   - only when ONEFILE=1 is set in the
                                  environment (slower startup; not used by the
                                  installer).
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
PROJECT_ROOT = SPEC_DIR.parent
SRC = PROJECT_ROOT / "src"

APP_NAME = "PDF Batch Separator"
ONEFILE = os.environ.get("ONEFILE", "0") == "1"

ICON = PROJECT_ROOT / "src" / "pdf_batch_separator" / "resources" / "app.ico"
icon_arg = str(ICON) if ICON.exists() else None

# PyMuPDF and zxing-cpp ship compiled extensions; make sure their native
# libraries are collected even when the hooks miss them.
binaries = []
for package in ("pymupdf", "fitz", "zxingcpp"):
    try:
        binaries += collect_dynamic_libs(package)
    except Exception:
        pass

hiddenimports = [
    "pdf_batch_separator",
    "pdf_batch_separator.app",
    "pdf_batch_separator.ui.main_window",
    "pdf_batch_separator.ui.batch_model",
    "pdf_batch_separator.ui.batch_delegate",
    "pdf_batch_separator.ui.components",
    "pdf_batch_separator.ui.document_review",
    "pdf_batch_separator.ui.icons",
    "pdf_batch_separator.ui.theme",
    "pdf_batch_separator.workers",
    # The interface icons are SVG, so the Qt SVG module and its image plugin
    # must ship with the build or every glyph would silently disappear.
    "PySide6.QtSvg",
    "pymupdf",
    "zxingcpp",
    "numpy",
]
hiddenimports += collect_submodules("pdf_batch_separator")

datas = []
resources = SRC / "pdf_batch_separator" / "resources"
if resources.is_dir():
    datas.append((str(resources), "pdf_batch_separator/resources"))
for document in ("THIRD_PARTY_NOTICES.md", "LICENSE", "PRIVACY.md"):
    candidate = PROJECT_ROOT / document
    if candidate.exists():
        datas.append((str(candidate), "."))

# Trim modules the application never uses.  This keeps the installer small and
# removes network/telemetry-capable code paths we do not need.
excludes = [
    "tkinter",
    "unittest",
    "pydoc_data",
    "test",
    "pytest",
    "setuptools",
    "pip",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtNetworkAuth",
    "PySide6.QtBluetooth",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQml",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
]

block_cipher = None

# PyInstaller compiles this entry script as the program's top-level ``__main__``
# module, which means it runs with no parent package (``__package__`` is empty).
# It must therefore use absolute imports only - a relative import such as
# ``from .app import main`` raises "attempted relative import with no known
# parent package" and the application dies at launch with nothing but a
# "Failed to execute script" dialog.  tests/test_packaging.py enforces this.
#
# Because the entry script imports the application lazily (inside a function),
# static analysis cannot follow it, so ``pdf_batch_separator.app`` is declared
# in hiddenimports above and collect_submodules() sweeps up the rest.
a = Analysis(
    [str(SRC / "pdf_batch_separator" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        runtime_tmpdir=None,
        console=False,          # GUI application: no console window
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_arg,
        version=str(SPEC_DIR / "version_info.txt")
        if (SPEC_DIR / "version_info.txt").exists()
        else None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,          # GUI application: no console window
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_arg,
        version=str(SPEC_DIR / "version_info.txt")
        if (SPEC_DIR / "version_info.txt").exists()
        else None,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
