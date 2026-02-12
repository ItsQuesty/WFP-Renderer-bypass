from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wfp_compiler.ffmpeg_runtime import FFmpegNotFoundError, resolve_ffmpeg_binaries
from wfp_compiler.models import QualityPreset, RenderEngine
from wfp_compiler.parser import parse_wfp_project
from wfp_compiler.renderer import render_project_to_mp4

from .helpers import create_minimal_wfp


def test_integration_render_outputs_valid_mp4(tmp_path: Path) -> None:
    try:
        binaries = resolve_ffmpeg_binaries()
    except FFmpegNotFoundError:
        pytest.skip("ffmpeg/ffprobe not available for integration test")

    source = tmp_path / "source.mp4"
    def build_source_cmd(video_codec: str) -> list[str]:
        return [
            str(binaries.ffmpeg_path),
            "-hide_banner",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=25:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=44100:duration=2",
            "-shortest",
            "-c:v",
            video_codec,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ]
    try:
        subprocess.run(build_source_cmd("libx264"), check=True)
    except subprocess.CalledProcessError:
        subprocess.run(build_source_cmd("mpeg4"), check=True)

    wfp = tmp_path / "integration.wfp"
    create_minimal_wfp(wfp, source, duration_us=18_000_000, width=1280, height=720, fps_num=25, fps_den=1)
    project = parse_wfp_project(wfp)

    output = tmp_path / "output.mp4"
    result = render_project_to_mp4(
        project=project,
        output_path=output,
        quality=QualityPreset.LOW,
        ffmpeg_binaries=binaries,
        engine=RenderEngine.V1,
    )

    assert result.success, result.error
    assert output.exists() and output.stat().st_size > 0

    probe_cmd = [
        str(binaries.ffprobe_path),
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height",
        "-of",
        "json",
        str(output),
    ]
    probe = subprocess.run(probe_cmd, check=True, capture_output=True, text=True)
    payload = json.loads(probe.stdout)

    streams = payload.get("streams", [])
    assert any(stream.get("codec_type") == "video" for stream in streams)
    assert any(stream.get("codec_type") == "audio" for stream in streams)

    video_stream = next(stream for stream in streams if stream.get("codec_type") == "video")
    assert int(video_stream.get("width", 0)) == 1280
    assert int(video_stream.get("height", 0)) == 720

    duration = float(payload["format"]["duration"])
    assert 1.6 <= duration <= 2.1
