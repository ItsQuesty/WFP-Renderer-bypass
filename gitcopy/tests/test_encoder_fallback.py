from __future__ import annotations

from pathlib import Path

from wfp_compiler.ffmpeg_graph import FFmpegGraph
from wfp_compiler.ffmpeg_runtime import FFmpegBinaries
from wfp_compiler.models import QualityPreset, RenderEngine
from wfp_compiler.parser import parse_wfp_project
from wfp_compiler import renderer

from .helpers import create_minimal_wfp


def test_encoder_fallback_retries_and_succeeds_on_cpu(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "source.mp4"
    media.write_bytes(b"fake")

    wfp = tmp_path / "fallback.wfp"
    create_minimal_wfp(wfp, media)
    project = parse_wfp_project(wfp)

    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"x")
    ffprobe.write_bytes(b"x")
    binaries = FFmpegBinaries(ffmpeg, ffprobe)

    monkeypatch.setattr(
        renderer,
        "build_filter_graph",
        lambda plan, audio_repair=False: FFmpegGraph([], "anullsrc=r=44100:cl=stereo[aout];color=s=320x240:d=1[vout]"),
    )
    monkeypatch.setattr(renderer, "list_available_video_encoders", lambda _binaries: {"h264_amf", "libx264"})

    attempted: list[str] = []

    def fake_run_ffmpeg_once(**kwargs):
        encoder = kwargs["encoder"]
        attempted.append(encoder)
        if encoder == "h264_amf":
            return False, "simulated gpu failure"
        return True, ""

    monkeypatch.setattr(renderer, "_run_ffmpeg_once", fake_run_ffmpeg_once)

    result = renderer.render_project_to_mp4(
        project=project,
        output_path=tmp_path / "out.mp4",
        quality=QualityPreset.BALANCED,
        ffmpeg_binaries=binaries,
        engine=RenderEngine.V1,
    )

    assert result.success
    assert result.encoder == "libx264"
    assert attempted == ["h264_amf", "libx264"]
