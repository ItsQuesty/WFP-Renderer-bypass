from __future__ import annotations

import json
from pathlib import Path

from wfp_compiler.parser import parse_wfp_project

from .helpers import create_minimal_wfp


def test_parser_preserves_raw_extra_and_keyframes(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    wfp = tmp_path / "parser_v2.wfp"

    create_minimal_wfp(
        wfp,
        media,
        extra_video_clip_fields={"unknownCustomField": {"enabled": True}},
        extra_audio_clip_fields={
            "volumeKeyframe": {
                "parameter": json.dumps(
                    {
                        "Version": 3,
                        "ParameterType": 0,
                        "keyframeSets": [
                            {"_time": 0.0, "_value": -2.0},
                            {"_time": 1.0, "_value": -6.0},
                        ],
                    }
                )
            }
        },
    )

    project = parse_wfp_project(wfp)
    video_clip = project.video_tracks[0].clips[0]
    audio_clip = project.audio_tracks[0].clips[0]

    assert "unknownCustomField" in video_clip.raw_extra
    assert len(video_clip.speed_keyframes) >= 2
    assert len(audio_clip.volume_keyframes) == 2
