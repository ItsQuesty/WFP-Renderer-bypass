from __future__ import annotations

from pathlib import Path

from wfp_compiler.parser import parse_wfp_project

from .helpers import create_minimal_wfp


def test_parse_wfp_project_extracts_timeline_fields(tmp_path: Path) -> None:
    media = tmp_path / "clip one.mp4"
    media.write_bytes(b"not-a-real-video")

    wfp = tmp_path / "sample.wfp"
    create_minimal_wfp(wfp, media, duration_us=3_500_000, fps_num=30, fps_den=1, width=1920, height=1080)

    project = parse_wfp_project(wfp)

    assert project.info.timeline_duration_us == 3_500_000
    assert project.info.fps_num == 30
    assert project.info.fps_den == 1
    assert project.info.width == 1920
    assert project.info.height == 1080
    assert project.video_tracks

    first_video_clip = project.video_tracks[0].clips[0]
    assert first_video_clip.source_path.name == "clip one.mp4"
    assert first_video_clip.in_point_us == 0
    assert first_video_clip.out_point_us == 3_500_000
