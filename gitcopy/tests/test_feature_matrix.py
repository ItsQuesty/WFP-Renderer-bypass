from __future__ import annotations

from pathlib import Path

from wfp_compiler.feature_check import build_feature_check_rows
from wfp_compiler.models import RenderEngine
from wfp_compiler.parser import parse_wfp_project

from .helpers import create_minimal_wfp


def test_feature_check_rows_include_core_sections(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    wfp = tmp_path / "matrix.wfp"
    create_minimal_wfp(wfp, media, include_color_effect=True, add_second_video_track=True)

    project = parse_wfp_project(wfp)
    rows = build_feature_check_rows(project, engine=RenderEngine.V2)

    names = [row[0] for row in rows]
    assert "Multi-track video" in names
    assert "Speed curves / reverse" in names
    assert "AI effects" in names


def test_feature_check_rows_v1_marks_multitrack_partial(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    wfp = tmp_path / "matrix_v1.wfp"
    create_minimal_wfp(wfp, media, add_second_video_track=True)

    project = parse_wfp_project(wfp)
    rows = build_feature_check_rows(project, engine=RenderEngine.V1)

    row_by_name = {name: (status, details) for name, status, details in rows}
    assert row_by_name["Multi-track video"][0] == "Partial"
