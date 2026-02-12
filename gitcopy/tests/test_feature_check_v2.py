from __future__ import annotations

from pathlib import Path

from wfp_compiler.feature_check import analyze_project_features
from wfp_compiler.models import RenderEngine
from wfp_compiler.parser import parse_wfp_project

from .helpers import create_minimal_wfp


def test_feature_check_v2_does_not_emit_v1_track_warning(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    wfp = tmp_path / "feature_v2.wfp"
    create_minimal_wfp(wfp, media, add_second_video_track=True)

    project = parse_wfp_project(wfp)
    warnings = analyze_project_features(project, engine=RenderEngine.V2)

    assert not any("Only the first video track is rendered in v1" in warning for warning in warnings)
