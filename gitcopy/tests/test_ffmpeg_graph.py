from __future__ import annotations

from pathlib import Path

from wfp_compiler.ffmpeg_graph import build_filter_graph
from wfp_compiler.parser import parse_wfp_project
from wfp_compiler.renderer import build_render_plan

from .helpers import create_minimal_wfp


def test_ffmpeg_graph_contains_concat_mix_and_gap_segment(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake")

    wfp = tmp_path / "graph.wfp"
    create_minimal_wfp(wfp, media, duration_us=3_000_000)
    project = parse_wfp_project(wfp)

    video_clip = project.video_tracks[0].clips[0]
    audio_clip = project.audio_tracks[0].clips[0]

    video_clip.tl_end_us = 2_000_000
    video_clip.out_point_us = 2_000_000
    audio_clip.tl_end_us = 2_000_000
    audio_clip.out_point_us = 2_000_000

    plan = build_render_plan(project)
    graph = build_filter_graph(plan)

    assert "concat=n=" in graph.filter_complex
    assert "amix=inputs=" in graph.filter_complex
    assert "color=c=black" in graph.filter_complex
    assert graph.input_files


def test_ffmpeg_graph_audio_repair_filters_when_enabled(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake")

    wfp = tmp_path / "graph_audio_repair.wfp"
    create_minimal_wfp(wfp, media, duration_us=2_000_000)
    project = parse_wfp_project(wfp)
    plan = build_render_plan(project)

    graph_plain = build_filter_graph(plan, audio_repair=False)
    graph_repair = build_filter_graph(plan, audio_repair=True)

    assert "highpass=f=100" not in graph_plain.filter_complex
    assert "dynaudnorm=" not in graph_plain.filter_complex

    assert "highpass=f=100" in graph_repair.filter_complex
    assert "dynaudnorm=" in graph_repair.filter_complex
    assert "acompressor=" in graph_repair.filter_complex
    assert "alimiter=" in graph_repair.filter_complex
