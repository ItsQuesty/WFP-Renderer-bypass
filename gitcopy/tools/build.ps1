$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

python -m pip install -e .[dev]

$ffmpeg = Join-Path $RepoRoot "vendor\ffmpeg\windows-x64\ffmpeg.exe"
$ffprobe = Join-Path $RepoRoot "vendor\ffmpeg\windows-x64\ffprobe.exe"

if (-not (Test-Path $ffmpeg) -or -not (Test-Path $ffprobe)) {
    Write-Host "Bundled FFmpeg not found. Fetching now..."
    & (Join-Path $RepoRoot "tools\fetch_ffmpeg.ps1")
}

python -m PyInstaller --noconfirm --clean WfpCompiler.spec

Write-Host "Build complete. Output executable: dist\WfpCompiler.exe"
