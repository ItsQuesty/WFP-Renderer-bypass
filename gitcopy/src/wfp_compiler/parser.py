from __future__ import annotations

import base64
import json
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .models import Clip, ParsedProject, ProjectInfo, ResourceInfo, Track


class WfpParseError(RuntimeError):
    """Raised when a .wfp file cannot be parsed."""


def parse_wfp_project(wfp_path: str | Path) -> ParsedProject:
    wfp_path = Path(wfp_path).expanduser().resolve()
    if not wfp_path.exists():
        raise WfpParseError(f"File does not exist: {wfp_path}")

    parser_warnings: list[str] = []

    with zipfile.ZipFile(wfp_path, "r") as zf:
        project_info = _read_json_from_zip(zf, "ProjectFolder/project_info.json")
        timeline_media_id = project_info.get("timeline_mediaId")
        if not timeline_media_id:
            raise WfpParseError("project_info.json missing timeline_mediaId")

        timeline_path = f"ProjectFolder/Medias/{timeline_media_id}/timeline.wesproj"
        timeline_root = _read_json_from_zip(zf, timeline_path)

        timeline_infos = timeline_root.get("timelineInfos")
        if not isinstance(timeline_infos, list) or not timeline_infos:
            raise WfpParseError("timeline.wesproj missing timelineInfos")
        timeline = timeline_infos[0]

        frame_rate = timeline.get("frameRate") or {}
        fps_num = int(frame_rate.get("num", 30) or 30)
        fps_den = int(frame_rate.get("den", 1) or 1)

        project = ProjectInfo(
            file_name=str(project_info.get("project_file_name") or wfp_path.stem),
            timeline_media_id=str(timeline_media_id),
            timeline_duration_us=int(project_info.get("project_timeline_duration") or 0),
            fps_num=fps_num,
            fps_den=fps_den,
            width=int(timeline.get("resolutionWidth") or 1920),
            height=int(timeline.get("resolutionHeight") or 1080),
            sample_rate=int(timeline.get("sampleRate") or project_info.get("project_sample_rate") or 44100),
            timeline_path_in_zip=timeline_path,
        )

        resources_by_uuid = _parse_resources(timeline_root.get("resources") or [])

        track_infos = timeline.get("trackInfos")
        if not isinstance(track_infos, list):
            raise WfpParseError("timeline.wesproj missing trackInfos")

        tracks: list[Track] = []
        for track_index, track_obj in enumerate(track_infos):
            track_type = int(_first(track_obj, "trackType", "type", default=0))
            clip_list = _first(track_obj, "clipList", "clips", default=[])
            if not isinstance(clip_list, list):
                clip_list = []

            clips: list[Clip] = []
            for clip_obj in clip_list:
                clip = _parse_clip(clip_obj, track_type)
                if clip is None:
                    parser_warnings.append(
                        f"Skipped malformed clip in track {track_index} ({track_obj.get('uuid', 'unknown')})."
                    )
                    continue
                clips.append(clip)

            track_known_keys = {"trackType", "type", "trackTag", "uuid", "clipList", "clips"}
            tracks.append(
                Track(
                    index=track_index,
                    track_type=track_type,
                    track_tag=_optional_int(_first(track_obj, "trackTag", "tag", default=None)),
                    uuid=str(_first(track_obj, "uuid", "id", default=f"track-{track_index}")),
                    clips=clips,
                    raw_extra=_extract_raw_extra(track_obj, track_known_keys),
                )
            )

    parsed_known_keys = {
        "timelineInfos",
        "resources",
        "currentTimelineId",
        "productName",
        "projectName",
        "serialNumber",
        "serializationVersion",
    }
    return ParsedProject(
        wfp_path=wfp_path,
        info=project,
        tracks=tracks,
        resources_by_uuid=resources_by_uuid,
        parser_warnings=parser_warnings,
        raw_extra=_extract_raw_extra(timeline_root, parsed_known_keys),
    )


def normalize_file_uri_to_path(uri_or_path: str) -> Path:
    if uri_or_path.startswith("file:/"):
        parsed = urlparse(uri_or_path)
        path_part = parsed.path or uri_or_path[len("file:/") :]
        path_part = unquote(path_part)
        if path_part.startswith("/") and len(path_part) > 2 and path_part[2] == ":":
            path_part = path_part[1:]
        return Path(path_part.replace("/", "\\"))
    return Path(uri_or_path)


def _read_json_from_zip(zf: zipfile.ZipFile, entry_name: str) -> dict[str, Any]:
    try:
        with zf.open(entry_name, "r") as fp:
            raw = fp.read().decode("utf-8")
    except KeyError as exc:
        raise WfpParseError(f"Missing entry in .wfp: {entry_name}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WfpParseError(f"Invalid JSON in {entry_name}: {exc}") from exc


def _parse_resources(resource_list: list[Any]) -> dict[str, ResourceInfo]:
    resources: dict[str, ResourceInfo] = {}
    for resource in resource_list:
        if not isinstance(resource, dict):
            continue

        source_uuid = _first(resource, "sourceUuid", "uuid", "id")
        filename = _first(resource, "filename", "path", "filePath", "sourcePath")
        if not source_uuid or not filename:
            continue

        known_keys = {
            "sourceUuid",
            "uuid",
            "id",
            "filename",
            "path",
            "filePath",
            "sourcePath",
            "videoStreamCount",
            "audioStreamCount",
            "videoCount",
            "audioCount",
            "streamType",
        }
        resources[str(source_uuid)] = ResourceInfo(
            source_uuid=str(source_uuid),
            path=normalize_file_uri_to_path(str(filename)),
            video_stream_count=int(_first(resource, "videoStreamCount", "videoCount", default=0) or 0),
            audio_stream_count=int(_first(resource, "audioStreamCount", "audioCount", default=0) or 0),
            raw_extra=_extract_raw_extra(resource, known_keys),
        )

    return resources


def _parse_clip(clip_obj: Any, track_type: int) -> Clip | None:
    if not isinstance(clip_obj, dict):
        return None

    source_uuid = str(_first(clip_obj, "sourceUuid", "mediaUuid", "mediaId", default=""))
    filename = str(_first(clip_obj, "filename", "path", "filePath", "sourcePath", default=""))
    if not filename:
        return None

    effect_ids: list[str] = []
    effect_params: dict[str, dict[str, Any]] = {}
    volume_gain_db: float | None = None
    has_transform = False
    has_crop_pan_zoom = False

    effect_chain_list = _first(clip_obj, "effectChainList", "effectChains", default=[])
    if isinstance(effect_chain_list, list):
        for chain in effect_chain_list:
            if not isinstance(chain, dict):
                continue
            effect_list = _first(chain, "effectList", "effects", default=[])
            if not isinstance(effect_list, list):
                continue

            for effect in effect_list:
                if not isinstance(effect, dict):
                    continue
                effect_id = str(_first(effect, "id", "effectId", "name", default=""))
                if not effect_id:
                    continue
                effect_ids.append(effect_id)
                if effect_id == "video/effect/transform":
                    has_transform = True
                if effect_id == "video/effect/crop-pan-zoom":
                    has_crop_pan_zoom = True

                if effect_id == "audio/effect/volume":
                    parsed_gain = _parse_volume_gain(effect)
                    if parsed_gain is not None:
                        volume_gain_db = parsed_gain

                parsed_effect_params = _parse_effect_params(effect)
                if parsed_effect_params:
                    effect_params[effect_id] = parsed_effect_params

    speed_reverse, speed_non_trivial, speed_keyframes = _parse_speed_flags(_first(clip_obj, "speed", default=None))

    volume_kf = _parse_keyframe_field(_first(clip_obj, "volumeKeyframe", default=None))
    ducking_kf = _parse_keyframe_field(_first(clip_obj, "audioDuckingframe", "audioDuckingKeyframe", default=None))

    flags: list[str] = []
    if volume_kf:
        flags.append("volume_keyframes")
    if ducking_kf:
        flags.append("audio_ducking_keyframes")

    user_data = _first(clip_obj, "userData", "userdata", default=[])
    if isinstance(user_data, list):
        if _has_enabled_ai_user_data(user_data):
            flags.append("ai_user_data")

    stabilization = _first(clip_obj, "stabilization", default=None)
    if isinstance(stabilization, dict) and int(stabilization.get("status") or 0) != 0:
        flags.append("stabilization")

    known_keys = {
        "thisUId",
        "thisUid",
        "uuid",
        "id",
        "sourceUuid",
        "mediaUuid",
        "mediaId",
        "filename",
        "path",
        "filePath",
        "sourcePath",
        "type",
        "clipType",
        "streamId",
        "audioStreamIndex",
        "tlBegin",
        "timelineStart",
        "tlEnd",
        "timelineEnd",
        "inPoint",
        "sourceIn",
        "outPoint",
        "sourceOut",
        "speed",
        "effectChainList",
        "effectChains",
        "volumeKeyframe",
        "audioDuckingframe",
        "audioDuckingKeyframe",
        "userData",
        "userdata",
        "stabilization",
    }

    return Clip(
        this_uid=str(_first(clip_obj, "thisUId", "thisUid", "uuid", "id", default="")),
        source_uuid=source_uuid,
        source_path=normalize_file_uri_to_path(filename),
        track_type=track_type,
        clip_type=int(_first(clip_obj, "type", "clipType", default=0) or 0),
        stream_id=int(_first(clip_obj, "streamId", "audioStreamIndex", default=0) or 0),
        tl_begin_us=int(_first(clip_obj, "tlBegin", "timelineStart", default=0) or 0),
        tl_end_us=int(_first(clip_obj, "tlEnd", "timelineEnd", default=0) or 0),
        in_point_us=int(_first(clip_obj, "inPoint", "sourceIn", default=0) or 0),
        out_point_us=int(_first(clip_obj, "outPoint", "sourceOut", default=0) or 0),
        volume_gain_db=volume_gain_db,
        has_transform=has_transform,
        has_crop_pan_zoom=has_crop_pan_zoom,
        effect_ids=tuple(sorted(set(effect_ids))),
        effect_params=effect_params,
        speed_reverse=speed_reverse,
        speed_non_trivial=speed_non_trivial,
        speed_keyframes=tuple(speed_keyframes),
        volume_keyframes=tuple(volume_kf),
        ducking_keyframes=tuple(ducking_kf),
        flags=tuple(sorted(set(flags))),
        raw_extra=_extract_raw_extra(clip_obj, known_keys),
    )


def _parse_volume_gain(effect_obj: dict[str, Any]) -> float | None:
    param_list = _first(effect_obj, "paramList", "params", default=[])
    if not isinstance(param_list, list):
        return None

    for param in param_list:
        if not isinstance(param, dict):
            continue
        name = str(_first(param, "name", "paramName", default=""))
        if name not in {"VolumeGain", "volumeGain", "gain"}:
            continue
        fx_param = _first(param, "fxParam", "value", default=None)
        if isinstance(fx_param, dict):
            value = _first(fx_param, "unValue", "value", default=None)
        else:
            value = fx_param
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _parse_effect_params(effect_obj: dict[str, Any]) -> dict[str, Any]:
    param_list = _first(effect_obj, "paramList", "params", default=[])
    if not isinstance(param_list, list):
        return {}

    result: dict[str, Any] = {}
    for param in param_list:
        if not isinstance(param, dict):
            continue
        name = str(_first(param, "name", "paramName", default=""))
        if not name:
            continue
        fx_param = _first(param, "fxParam", "value", default=None)
        if isinstance(fx_param, dict):
            value = _first(fx_param, "unValue", "value", default=None)
        else:
            value = fx_param
        if value is not None:
            result[name] = value

    return result


def _parse_speed_flags(speed_obj: Any) -> tuple[bool, bool, list[tuple[float, float]]]:
    if not isinstance(speed_obj, dict):
        return False, False, []

    reverse = bool(speed_obj.get("reverse"))
    non_trivial = reverse

    speed_param = speed_obj.get("speedParam")
    parsed_param: dict[str, Any] | None = None
    points: list[tuple[float, float]] = []

    if isinstance(speed_param, dict):
        parsed_param = speed_param
    elif isinstance(speed_param, str) and speed_param.strip():
        try:
            parsed_param = json.loads(speed_param)
        except json.JSONDecodeError:
            non_trivial = True

    if isinstance(parsed_param, dict):
        keyframes = parsed_param.get("keyframeSets")
        if isinstance(keyframes, list) and keyframes:
            for frame in keyframes:
                if not isinstance(frame, dict):
                    continue
                try:
                    time_s = float(frame.get("_time"))
                    value = float(frame.get("_value"))
                except (TypeError, ValueError):
                    non_trivial = True
                    continue
                points.append((time_s, value))
                if abs(value - 1.0) > 1e-6:
                    non_trivial = True
            points.sort(key=lambda item: item[0])
            if len(points) > 2:
                non_trivial = True

    return reverse, non_trivial, points


def _parse_keyframe_field(field_obj: Any) -> list[tuple[float, float]]:
    if not isinstance(field_obj, dict):
        return []

    parameter = field_obj.get("parameter")
    if isinstance(parameter, dict):
        parsed = parameter
    elif isinstance(parameter, str) and parameter.strip():
        try:
            parsed = json.loads(parameter)
        except json.JSONDecodeError:
            return []
    else:
        return []

    if not isinstance(parsed, dict):
        return []
    keyframes = parsed.get("keyframeSets")
    if not isinstance(keyframes, list):
        return []

    result: list[tuple[float, float]] = []
    for frame in keyframes:
        if not isinstance(frame, dict):
            continue
        try:
            time_s = float(frame.get("_time"))
            value = float(frame.get("_value"))
        except (TypeError, ValueError):
            continue
        result.append((time_s, value))
    result.sort(key=lambda item: item[0])
    return result


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first(obj: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return default


def _extract_raw_extra(obj: Any, known_keys: set[str]) -> dict[str, Any]:
    if not isinstance(obj, dict):
        return {}
    return {str(key): value for key, value in obj.items() if str(key) not in known_keys}


def _has_enabled_ai_user_data(user_data_list: list[Any]) -> bool:
    for item in user_data_list:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        if key not in {"73", "74"}:
            continue
        encoded = item.get("data")
        if not isinstance(encoded, str) or not encoded:
            continue
        try:
            raw = base64.b64decode(encoded).decode("utf-8", errors="ignore")
            payload = json.loads(raw)
        except Exception:
            continue

        effect_list = payload.get("effectList")
        if not isinstance(effect_list, list):
            continue
        for effect in effect_list:
            if isinstance(effect, dict) and bool(effect.get("enable")):
                return True
    return False
