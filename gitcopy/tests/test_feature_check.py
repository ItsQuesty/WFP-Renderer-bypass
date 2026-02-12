from __future__ import annotations

from pathlib import Path

from wfp_compiler.feature_check import analyze_project_features
from wfp_compiler.parser import parse_wfp_project

from .helpers import create_minimal_wfp


def test_feature_check_flags_unsupported_effects_and_speed(tmp_path: Path) -> None:
    media = tmp_path / "media.mp4"
    media.write_bytes(b"x")

    wfp = tmp_path / "feature.wfp"
    create_minimal_wfp(
        wfp,
        media,
        include_extra_effect=True,
        speed_values=[1.0, 1.25],
    )

    project = parse_wfp_project(wfp)
    warnings = analyze_project_features(project)

    # Default/no-param equalizer is treated as supported no-op in v1.
    assert not any("audio/effect/equalizer" in warning for warning in warnings)
    assert any("non-trivial speed" in warning for warning in warnings)
