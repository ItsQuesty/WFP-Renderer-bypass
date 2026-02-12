from __future__ import annotations

import json
import zipfile
from pathlib import Path
from urllib.parse import quote


def to_file_uri(path: Path) -> str:
    return "file:/" + quote(path.as_posix(), safe=":/")


def create_minimal_wfp(
    output_path: Path,
    video_path: Path,
    *,
    duration_us: int = 20_000_000,
    fps_num: int = 25,
    fps_den: int = 1,
    width: int = 1280,
    height: int = 720,
    volume_gain_db: float = -6.0,
    include_extra_effect: bool = False,
    speed_reverse: bool = False,
    speed_values: list[float] | None = None,
    audio_clip_stream_id: int = 0,
    resource_video_stream_count: int = 1,
    resource_audio_stream_count: int = 1,
    extra_video_clip_fields: dict[str, object] | None = None,
    extra_audio_clip_fields: dict[str, object] | None = None,
    add_second_video_track: bool = False,
    include_color_effect: bool = False,
) -> Path:
    timeline_media_id = "{11111111-1111-1111-1111-111111111111}"
    source_uuid = "source-uuid-1"

    if speed_values is None:
        speed_values = [1.0, 1.0]

    speed_param = {
        "Version": 3,
        "ParameterType": 0,
        "keyframeSets": [
            {"_time": 0.0, "Interpolation": 6, "_value": speed_values[0]},
            {"_time": duration_us / 10_000_000.0, "Interpolation": 6, "_value": speed_values[-1]},
        ],
        "_totalTime": duration_us / 10_000_000.0,
    }

    project_info = {
        "project_file_name": output_path.stem,
        "project_timeline_duration": duration_us,
        "project_timeline_framerate": [fps_num, fps_den],
        "project_timeline_resolution": [width, height],
        "project_sample_rate": 44100,
        "timeline_mediaId": timeline_media_id,
    }

    audio_effects = [
        {
            "display": "volume",
            "id": "audio/effect/volume",
            "paramList": [
                {
                    "name": "VolumeGain",
                    "fxParam": {"paramType": 2, "unValue": volume_gain_db},
                }
            ],
            "type": 3,
        }
    ]

    if include_extra_effect:
        audio_effects.append({"display": "equalizer", "id": "audio/effect/equalizer", "type": 3})

    video_effects = [
        {"display": "crop-pan-zoom", "id": "video/effect/crop-pan-zoom", "type": 3},
        {
            "display": "transform",
            "id": "video/effect/transform",
            "type": 3,
            "paramList": [
                {"name": "dwValue", "fxParam": {"paramType": 5, "unValue": 1186339}},
                {"name": "EnableTransform", "fxParam": {"paramType": 5, "unValue": 1}},
            ],
        },
    ]
    if include_color_effect:
        video_effects.append(
            {
                "display": "color",
                "id": "video/effect/color/basic",
                "type": 3,
                "paramList": [
                    {"name": "brightness", "fxParam": {"paramType": 5, "unValue": 0.1}},
                    {"name": "contrast", "fxParam": {"paramType": 5, "unValue": 1.2}},
                ],
            }
        )

    video_clip = {
        "thisUId": "video-clip-1",
        "type": 1,
        "sourceUuid": source_uuid,
        "filename": to_file_uri(video_path),
        "streamId": 0,
        "tlBegin": 0,
        "tlEnd": duration_us,
        "inPoint": 0,
        "outPoint": duration_us,
        "speed": {
            "offset": 0.0,
            "offsetEnd": duration_us / 10_000_000.0,
            "reverse": speed_reverse,
            "speedParam": json.dumps(speed_param),
        },
        "effectChainList": [
            {
                "name": "Basic",
                "effectList": video_effects,
            }
        ],
        "userData": [],
    }

    audio_clip = {
        "thisUId": "audio-clip-1",
        "type": 2,
        "sourceUuid": source_uuid,
        "filename": to_file_uri(video_path),
        "streamId": audio_clip_stream_id,
        "tlBegin": 0,
        "tlEnd": duration_us,
        "inPoint": 0,
        "outPoint": duration_us,
        "speed": {
            "offset": 0.0,
            "offsetEnd": duration_us / 10_000_000.0,
            "reverse": speed_reverse,
            "speedParam": json.dumps(speed_param),
        },
        "effectChainList": [
            {
                "name": "BasicFollow",
                "effectList": audio_effects,
            }
        ],
        "volumeKeyframe": {
            "parameter": json.dumps({"Version": 3, "ParameterType": 0, "keyframeSets": []}),
        },
        "audioDuckingframe": {
            "parameter": json.dumps({"Version": 3, "ParameterType": 0, "keyframeSets": []}),
        },
        "userData": [],
    }
    if extra_video_clip_fields:
        video_clip.update(extra_video_clip_fields)
    if extra_audio_clip_fields:
        audio_clip.update(extra_audio_clip_fields)

    track_infos = [
        {
            "trackType": 2,
            "trackTag": 1,
            "uuid": "track-a-1",
            "clipList": [audio_clip],
        },
        {
            "trackType": 1,
            "trackTag": 2,
            "uuid": "track-v-1",
            "clipList": [video_clip],
        },
    ]
    if add_second_video_track:
        second_clip = dict(video_clip)
        second_clip["thisUId"] = "video-clip-2"
        second_clip["tlBegin"] = max(0, duration_us // 4)
        second_clip["tlEnd"] = max(second_clip["tlBegin"] + 1_000_000, duration_us - duration_us // 8)
        second_clip["outPoint"] = min(duration_us, second_clip["tlEnd"] - second_clip["tlBegin"])
        second_clip["inPoint"] = 0
        track_infos.append(
            {
                "trackType": 1,
                "trackTag": 2,
                "uuid": "track-v-2",
                "clipList": [second_clip],
            }
        )

    timeline = {
        "currentTimelineId": 1,
        "productName": "Filmora",
        "projectName": "test",
        "resources": [
            {
                "sourceUuid": source_uuid,
                "filename": to_file_uri(video_path),
                "videoStreamCount": resource_video_stream_count,
                "audioStreamCount": resource_audio_stream_count,
                "streamType": 2,
            }
        ],
        "timelineInfos": [
            {
                "timelineId": 1,
                "resolutionWidth": width,
                "resolutionHeight": height,
                "sampleRate": 44100,
                "frameRate": {"num": fps_num, "den": fps_den},
                "trackInfos": track_infos,
                "type": 0,
                "userData": [],
            }
        ],
        "serialNumber": 1,
        "serializationVersion": "1.0",
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ProjectFolder/project_info.json", json.dumps(project_info))
        zf.writestr(
            f"ProjectFolder/Medias/{timeline_media_id}/timeline.wesproj",
            json.dumps(timeline),
        )

    return output_path
