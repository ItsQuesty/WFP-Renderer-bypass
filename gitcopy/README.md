# WFP Compiler

Windows-first renderer that opens Filmora `.wfp` project files and exports MP4 using FFmpeg (without Filmora's exporter).

## What It Does

- Parses Filmora-style `.wfp` ZIP projects.
- Resolves timeline clips/tracks and renders to MP4.
- Supports relinking missing media before export.
- Uses hardware encoders when available, with CPU fallback.
- Includes optional audio repair processing for speech cleanup.

## Important Notice

This project is not affiliated with Wondershare/Filmora.  
Use only where you have legal rights to the source content and project assets.

## Requirements

- Windows 10/11
- Python 3.10+
- FFmpeg binaries (fetched via `tools/fetch_ffmpeg.ps1` for local/dev builds)

## Quick Start (Dev)

```powershell
python -m pip install -e .[dev]
python -m pytest -q
python -m wfp_compiler gui
```

## CLI Usage

```powershell
python -m wfp_compiler render --input project.wfp --output output.mp4 --quality Balanced
```

Disable audio repair if needed:

```powershell
python -m wfp_compiler render --input project.wfp --output output.mp4 --no-audio-repair
```

Select engine explicitly (`v2` is default):

```powershell
python -m wfp_compiler render --input project.wfp --output output.mp4 --engine v2
```

Parity tooling:

```powershell
python -m wfp_compiler parity scan --manifest parity/manifest.example.json
python -m wfp_compiler parity run --manifest parity/manifest.example.json
python -m wfp_compiler parity effects --manifest parity/manifest.example.json
```

## Build EXE

```powershell
powershell -ExecutionPolicy Bypass -File tools\\fetch_ffmpeg.ps1
powershell -ExecutionPolicy Bypass -File tools\\build.ps1
```

Expected output:

- `dist/WfpCompiler.exe`

## Project Layout

- `src/wfp_compiler/gui.py`: desktop GUI
- `src/wfp_compiler/parser.py`: `.wfp` parsing
- `src/wfp_compiler/ffmpeg_graph.py`: FFmpeg filter graph construction
- `src/wfp_compiler/renderer.py`: render orchestration + encoder fallback
- `tests/`: parser/graph/gui/integration tests
- `tools/`: FFmpeg fetch + build scripts

## Contributing

See `CONTRIBUTING.md` for setup, style, and PR expectations.
