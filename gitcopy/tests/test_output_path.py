from __future__ import annotations

from pathlib import Path

from wfp_compiler.ffmpeg_graph import FFmpegGraph
from wfp_compiler.ffmpeg_runtime import FFmpegBinaries
from wfp_compiler.gui import WfpCompilerApp
from wfp_compiler.models import QualityPreset
from wfp_compiler.parser import parse_wfp_project
from wfp_compiler import renderer

from .helpers import create_minimal_wfp


def test_normalize_output_path_forces_mp4_suffix() -> None:
    assert renderer.normalize_output_path("clip") == Path("clip.mp4")
    assert renderer.normalize_output_path("clip.mkv") == Path("clip.mp4")
    assert renderer.normalize_output_path("clip.mp4") == Path("clip.mp4")


def test_default_output_for_project_uses_ripped_suffix() -> None:
    assert WfpCompilerApp._default_output_for_project(None, Path("movie.wfp")) == Path("movie_ripped.mp4")
    assert WfpCompilerApp._default_output_for_project(None, Path("Untitled (copy).wfp")) == Path(
        "Untitled (copy)_ripped.mp4"
    )
    assert WfpCompilerApp._default_output_for_project(None, Path("my.project.v2.wfp")) == Path(
        "my.project.v2_ripped.mp4"
    )


def test_render_uses_normalized_output_path(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "source.mp4"
    media.write_bytes(b"fake")

    wfp = tmp_path / "project.wfp"
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
    monkeypatch.setattr(renderer, "list_available_video_encoders", lambda _binaries: {"libx264"})

    seen_output_paths: list[Path] = []

    def fake_run_ffmpeg_once(**kwargs):
        seen_output_paths.append(kwargs["output_path"])
        return True, ""

    monkeypatch.setattr(renderer, "_run_ffmpeg_once", fake_run_ffmpeg_once)

    result = renderer.render_project_to_mp4(
        project=project,
        output_path=tmp_path / "no_extension_output",
        quality=QualityPreset.BALANCED,
        ffmpeg_binaries=binaries,
    )

    expected = tmp_path / "no_extension_output.mp4"
    assert result.success
    assert result.output_path == expected
    assert seen_output_paths == [expected]
