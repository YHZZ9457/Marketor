# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all
from pathlib import Path
import sys


ak_datas, ak_binaries, ak_hiddenimports = collect_all("akshare")
bs_datas, bs_binaries, bs_hiddenimports = collect_all("baostock")
python_root = Path(sys.base_prefix)
tk_datas = [
    (str(python_root / "Lib" / "tkinter"), "tkinter"),
    (str(python_root / "tcl" / "tcl8.6"), "_tcl_data"),
    (str(python_root / "tcl" / "tk8.6"), "_tk_data"),
]
tk_binaries = [
    (str(python_root / "DLLs" / "_tkinter.pyd"), "."),
    (str(python_root / "DLLs" / "tcl86t.dll"), "."),
    (str(python_root / "DLLs" / "tk86t.dll"), "."),
]

a = Analysis(
    ["packaging/marketor_entry.py"],
    pathex=["src"],
    binaries=ak_binaries + bs_binaries + tk_binaries,
    datas=[("data", "data"), ("assets/app-icon.ico", "assets")] + ak_datas + bs_datas + tk_datas,
    hiddenimports=ak_hiddenimports + bs_hiddenimports + ["tkinter", "tkinter.ttk", "tkinter.messagebox", "_tkinter"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["packaging/pyi_rth_tk_manual.py"],
    excludes=["pytest", "IPython", "jupyter", "notebook"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Marketor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/app-icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Marketor",
)
