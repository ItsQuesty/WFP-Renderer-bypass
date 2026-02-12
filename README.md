WFP Compiler (WFP-Renderer-bypass)

"i am become renderer, destroyer of watermarks"


A clean-room, external rendering engine for Wondershare Filmora 15 (.wfp) project files.

WFP Compiler parses project files and reconstructs the editing timeline using FFmpeg, allowing you to export projects to MP4 without using the Filmora engine, effectively bypassing watermarks and export restrictions without cracking or modifying the original software.

⚡ Core Features
External Rendering: Completely bypasses the Filmora export engine by interpreting .wfp files directly.

Hardware Acceleration: Automatically detects and utilizes NVIDIA (NVENC) or AMD (AMF) hardware encoders, with a seamless fallback to CPU encoding.

Advanced Audio Processing: Includes an optional audio repair pipeline for speech cleanup during the export.

Smart Relinking: Automatically attempts to resolve missing media paths before rendering begins.

Zero-Modification Policy: Operates strictly on the project save file (XML/JSON within ZIP). Does not inject code, crack executables, or modify Filmora installation files.

🔧 How It Works
Unlike "cracks" that patch binaries, WFP Compiler acts as a translation layer:

Parse: The parser module extracts the Edit Decision List (EDL) from the compressed .wfp package.

Graph Construction: The ffmpeg_graph module translates the Filmora timeline logic (cuts, tracks, overlays) into a complex FFmpeg filter graph.

Render: The renderer orchestrates the FFmpeg subprocess to compile the final video file.

📦 Installation & Usage
Option 1: Standalone EXE (Recommended)
Download the latest release from the Releases tab. No Python or FFmpeg installation required.

Option 2: Running from Source
Prerequisites:

Windows 10/11

Python 3.10+

Setup:

PowerShell

# Install dependencies
python -m pip install -e .[dev]

# Fetch required FFmpeg binaries
powershell -ExecutionPolicy Bypass -File tools\fetch_ffmpeg.ps1
GUI Mode:

PowerShell

python -m wfp_compiler gui
CLI Mode:

PowerShell

# Standard Render
python -m wfp_compiler render --input "C:\Path\To\Project.wfp" --output "output.mp4" --quality Balanced

# Render without Audio Repair
python -m wfp_compiler render --input "project.wfp" --output "output.mp4" --no-audio-repair
🏗️ Building the EXE
To build a standalone executable for distribution:

PowerShell

powershell -ExecutionPolicy Bypass -File tools\build.ps1
Output will be located in dist/WfpCompiler.exe.

⚠️ Legal & Disclaimer
This software is an interoperability tool and is NOT affiliated with Wondershare Technology.

This tool is designed for educational purposes and file interoperability.

It does not contain any code from Wondershare Filmora.

User Responsibility: You must ensure you have the legal right to use all source assets and media content in your project. The author is not responsible for misuse of this tool to bypass licensing terms you have agreed to.

🤝 Contributing
Contributions are welcome! Please check CONTRIBUTING.md for style guides and setup instructions. The project structure is as follows:

src/wfp_compiler/parser.py - Logic for reading .wfp structure

src/wfp_compiler/ffmpeg_graph.py - Logic for building render commands

src/wfp_compiler/gui.py - Frontend interface
