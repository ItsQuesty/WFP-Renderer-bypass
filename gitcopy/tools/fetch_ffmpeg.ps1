param(
    [string]$DownloadUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$VendorDir = Join-Path $RepoRoot "vendor\ffmpeg\windows-x64"
$TempDir = Join-Path $env:TEMP ("wfp-compiler-ffmpeg-" + [guid]::NewGuid().ToString("N"))
$ZipPath = Join-Path $TempDir "ffmpeg.zip"

New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
New-Item -ItemType Directory -Force -Path $VendorDir | Out-Null

Write-Host "Downloading FFmpeg from $DownloadUrl"
Invoke-WebRequest -Uri $DownloadUrl -OutFile $ZipPath

$ExtractDir = Join-Path $TempDir "extract"
Expand-Archive -Path $ZipPath -DestinationPath $ExtractDir -Force

$ffmpeg = Get-ChildItem -Path $ExtractDir -Recurse -Filter ffmpeg.exe | Select-Object -First 1
$ffprobe = Get-ChildItem -Path $ExtractDir -Recurse -Filter ffprobe.exe | Select-Object -First 1

if (-not $ffmpeg -or -not $ffprobe) {
    throw "Could not locate ffmpeg.exe and ffprobe.exe after extraction."
}

Copy-Item $ffmpeg.FullName (Join-Path $VendorDir "ffmpeg.exe") -Force
Copy-Item $ffprobe.FullName (Join-Path $VendorDir "ffprobe.exe") -Force

Write-Host "Bundled binaries copied to $VendorDir"

Remove-Item -Path $TempDir -Recurse -Force
