from __future__ import annotations

from pathlib import Path

from wfp_compiler.parser import parse_wfp_project
from wfp_compiler.timeline_v2 import build_timeline_v2

from .helpers import create_minimal_wfp


def test_timeline_v2_extracts_layering_titles_and_color(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    wfp = tmp_path / "timeline_v2.wfp"
    create_minimal_wfp(
        wfp,
        media,
        add_second_video_track=True,
        include_color_effect=True,
        extra_video_clip_fields={"text": "Hello v2"},
    )

    project = parse_wfp_project(wfp)
    timeline = build_timeline_v2(project)

    assert len(timeline.layered_video_clips) >= 2
    assert timeline.title_layers
    assert any(adjustments for adjustments in timeline.color_adjustments_by_clip.values())
