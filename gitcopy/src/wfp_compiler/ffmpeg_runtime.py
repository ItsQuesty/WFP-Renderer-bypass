from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class FFmpegNotFoundError(RuntimeError):
    """Raised when ffmpeg/ffprobe cannot be found."""


@dataclass(slots=True)
class FFmpegBinaries:
    ffmpeg_path: Path
    ffprobe_path: Path

    def ensure_exists(self) -> None:
        if not self.ffmpeg_path.exists():
            raise FFmpegNotFoundError(f"ffmpeg executable not found: {self.ffmpeg_path}")
        if not self.ffprobe_path.exists():
            raise FFmpegNotFoundError(f"ffprobe executable not found: {self.ffprobe_path}")


def resolve_ffmpeg_binaries(
    ffmpeg_path: str | Path | None = None,
    ffprobe_path: str | Path | None = None,
) -> FFmpegBinaries:
    if ffmpeg_path and ffprobe_path:
        binaries = FFmpegBinaries(Path(ffmpeg_path), Path(ffprobe_path))
        binaries.ensure_exists()
        return binaries

    bundled = _find_bundled_ffmpeg()
    if bundled:
        return bundled

    path_based = _find_path_ffmpeg()
    if path_based:
        return path_based

    common_locations = _find_common_windows_locations()
    if common_locations:
        return common_locations

    raise FFmpegNotFoundError(
        "Unable to find ffmpeg and ffprobe. Bundle them under vendor/ffmpeg/windows-x64 or install them on PATH."
    )


def list_available_video_encoders(binaries: FFmpegBinaries) -> set[str]:
    binaries.ensure_exists()
    command = [str(binaries.ffmpeg_path), "-hide_banner", "-encoders"]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    output = proc.stdout + "\n" + proc.stderr
    encoders: set[str] = set()

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        flags = parts[0]
        name = parts[1]
        if flags[0:1] == "V":
            encoders.add(name)

    return encoders


def choose_encoder_attempt_order(available_video_encoders: set[str]) -> list[str]:
    preferred = ["h264_amf", "h264_nvenc", "h264_qsv", "libx264"]
    ordered = [encoder for encoder in preferred if encoder in available_video_encoders]

    if not ordered and "libx264" not in available_video_encoders and available_video_encoders:
        # Last-resort fallback to any available H.264 video encoder.
        for name in sorted(available_video_encoders):
            if "264" in name:
                ordered.append(name)
                break

    if "libx264" in available_video_encoders and "libx264" not in ordered:
        ordered.append("libx264")

    return ordered


def _find_bundled_ffmpeg() -> FFmpegBinaries | None:
    candidate_roots: list[Path] = []

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate_roots.append(Path(meipass))

    package_root = Path(__file__).resolve().parents[2]
    candidate_roots.append(package_root)

    for root in candidate_roots:
        ffmpeg = root / "vendor" / "ffmpeg" / "windows-x64" / "ffmpeg.exe"
        ffprobe = root / "vendor" / "ffmpeg" / "windows-x64" / "ffprobe.exe"
        if ffmpeg.exists() and ffprobe.exists():
            return FFmpegBinaries(ffmpeg, ffprobe)

    return None


def _find_path_ffmpeg() -> FFmpegBinaries | None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        return FFmpegBinaries(Path(ffmpeg), Path(ffprobe))
    return None


def _find_common_windows_locations() -> FFmpegBinaries | None:
    candidates: list[tuple[Path, Path]] = [
        (
            Path(r"C:\Program Files\Virtual Desktop Streamer\ffmpeg.exe"),
            Path(r"C:\Program Files\Virtual Desktop Streamer\ffprobe.exe"),
        ),
        (
            Path.home() / "AppData" / "Roaming" / "Python" / "Python310" / "Scripts" / "ffmpeg.exe",
            Path.home() / "AppData" / "Roaming" / "Python" / "Python310" / "Scripts" / "ffprobe.exe",
        ),
    ]

    for ffmpeg, ffprobe in candidates:
        if ffmpeg.exists() and ffprobe.exists():
            return FFmpegBinaries(ffmpeg, ffprobe)

    return None
