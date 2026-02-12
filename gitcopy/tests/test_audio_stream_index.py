from __future__ import annotations

from pathlib import Path

from wfp_compiler.parser import parse_wfp_project
from wfp_compiler.renderer import build_render_plan

from .helpers import create_minimal_wfp


def test_audio_stream_index_is_normalized_from_absolute_stream_slot(tmp_path: Path) -> None:
    media = tmp_path / "media.mp4"
    media.write_bytes(b"x")

    wfp = tmp_path / "stream_map.wfp"
    create_minimal_wfp(
        wfp,
        media,
        audio_clip_stream_id=1,
        resource_video_stream_count=1,
        resource_audio_stream_count=1,
    )

    project = parse_wfp_project(wfp)
    plan = build_render_plan(project)

    assert plan.audio_segments
    assert plan.audio_segments[0].stream_id == 0

