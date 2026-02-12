# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path(SPECPATH)
ffmpeg_dir = project_root / "vendor" / "ffmpeg" / "windows-x64"

datas = []
if (ffmpeg_dir / "ffmpeg.exe").exists():
    datas.append((str(ffmpeg_dir / "ffmpeg.exe"), "vendor/ffmpeg/windows-x64"))
if (ffmpeg_dir / "ffprobe.exe").exists():
    datas.append((str(ffmpeg_dir / "ffprobe.exe"), "vendor/ffmpeg/windows-x64"))

a = Analysis(
    ["launch_gui.py"],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=["tkinter", "tkinter.ttk"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WfpCompiler",
    debug=False,
    strip=False,
    upx=True,
    console=False,
)
