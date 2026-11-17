# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for FM Name Editor.

Copyright (c) 2026 onwards Mark Hawksworth (hawkers63). All rights reserved.
Proprietary software, not open source. See LICENSE.

Build:  build_exe.bat   (or:  pyinstaller "FM Name Editor.spec")

A windowed, one-file build of fm_name_editor.py. The icon is carried
in alongside the script, and a Windows version resource names the
product, its version, and the copyright. PyInstaller is a build tool
only; PySide6 stays the one runtime dependency.
"""
import re
from pathlib import Path

HERE = Path(SPECPATH)


def _read_version() -> str:
    text = (HERE / "fm_name_editor.py").read_text(encoding="utf-8")
    match = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError("VERSION was not found in fm_name_editor.py")
    return match.group(1)


def _version_numbers(text: str) -> tuple:
    numbers = []
    for part in text.split("."):
        digits = re.match(r"\d+", part)
        numbers.append(int(digits.group(0)) if digits else 0)
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers[:4])


VERSION_TEXT = _read_version()
VERSION_NUMBERS = _version_numbers(VERSION_TEXT)
LEGAL_COPYRIGHT = (
    "Copyright (c) 2026 onwards Mark Hawksworth (hawkers63). All rights reserved.")

# Windows version resource (product name, file and product version, legal
# copyright). PyInstaller reads this file at build time; the kids blocks are
# the ones Windows Explorer shows under the exe's Details tab.
VERSION_FILE = HERE / "build" / "version_info.txt"
VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
VERSION_FILE.write_text(
    "# UTF-8\n"
    "VSVersionInfo(\n"
    "  ffi=FixedFileInfo(\n"
    f"    filevers={VERSION_NUMBERS!r},\n"
    f"    prodvers={VERSION_NUMBERS!r},\n"
    "    mask=0x3f,\n"
    "    flags=0x0,\n"
    "    OS=0x40004,\n"
    "    fileType=0x1,\n"
    "    subtype=0x0,\n"
    "    date=(0, 0),\n"
    "  ),\n"
    "  kids=[\n"
    "    StringFileInfo([\n"
    "      StringTable(\n"
    "        '040904B0',\n"
    "        [\n"
    "          StringStruct('CompanyName', 'Mark Hawksworth (hawkers63)'),\n"
    "          StringStruct('FileDescription', 'FM Name Editor'),\n"
    f"          StringStruct('FileVersion', '{VERSION_TEXT}'),\n"
    "          StringStruct('InternalName', 'FM Name Editor'),\n"
    f"          StringStruct('LegalCopyright', '{LEGAL_COPYRIGHT}'),\n"
    "          StringStruct('OriginalFilename', 'FM Name Editor.exe'),\n"
    "          StringStruct('ProductName', 'FM Name Editor'),\n"
    f"          StringStruct('ProductVersion', '{VERSION_TEXT}'),\n"
    "        ]),\n"
    "    ]),\n"
    "    VarFileInfo([VarStruct('Translation', [1033, 1200])]),\n"
    "  ]\n"
    ")\n",
    encoding="utf-8",
)


block_cipher = None

a = Analysis(
    ['fm_name_editor.py'],
    pathex=[str(HERE)],
    binaries=[],
    datas=[('icon/football.ico', 'icon')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='FM Name Editor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(HERE / 'icon' / 'football.ico'),
    version=str(VERSION_FILE),
)
