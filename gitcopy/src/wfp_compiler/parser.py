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
            track_type = int(track_obj.get("trackType") or 0)
            clip_list = track_obj.get("clipList")
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

            tracks.append(
                Track(
                    index=track_index,
                    track_type=track_type,
                    track_tag=_optional_int(track_obj.get("trackTag")),
                    uuid=str(track_obj.get("uuid") or f"track-{track_index}"),
                    clips=clips,
                )
            )

    return ParsedProject(
        wfp_path=wfp_path,
        info=project,
        tracks=tracks,
        resources_by_uuid=resources_by_uuid,
        parser_warnings=parser_warnings,
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

        source_uuid = resource.get("sourceUuid")
        filename = resource.get("filename")
        if not source_uuid or not filename:
            continue

        resources[str(source_uuid)] = ResourceInfo(
            source_uuid=str(source_uuid),
            path=normalize_file_uri_to_path(str(filename)),
            video_stream_count=int(resource.get("videoStreamCount") or 0),
            audio_stream_count=int(resource.get("audioStreamCount") or 0),
        )

    return resources


def _parse_clip(clip_obj: Any, track_type: int) -> Clip | None:
    if not isinstance(clip_obj, dict):
        return None

    source_uuid = str(clip_obj.get("sourceUuid") or "")
    filename = str(clip_obj.get("filename") or "")
    if not filename:
        return None

    effect_ids: list[str] = []
    effect_params: dict[str, dict[str, Any]] = {}
    volume_gain_db: float | None = None
    has_transform = False
    has_crop_pan_zoom = False

    effect_chain_list = clip_obj.get("effectChainList")
    if isinstance(effect_chain_list, list):
        for chain in effect_chain_list:
            if not isinstance(chain, dict):
                continue
            effect_list = chain.get("effectList")
            if not isinstance(effect_list, list):
                continue

            for effect in effect_list:
                if not isinstance(effect, dict):
                    continue
                effect_id = str(effect.get("id") or "")
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

    speed_reverse, speed_non_trivial = _parse_speed_flags(clip_obj.get("speed"))

    flags: list[str] = []
    if _has_non_empty_keyframe_param(clip_obj.get("volumeKeyframe")):
        flags.append("volume_keyframes")
    if _has_non_empty_keyframe_param(clip_obj.get("audioDuckingframe")):
        flags.append("audio_ducking_keyframes")

    user_data = clip_obj.get("userData")
    if isinstance(user_data, list):
        if _has_enabled_ai_user_data(user_data):
            flags.append("ai_user_data")

    stabilization = clip_obj.get("stabilization")
    if isinstance(stabilization, dict) and int(stabilization.get("status") or 0) != 0:
        flags.append("stabilization")

    return Clip(
        this_uid=str(clip_obj.get("thisUId") or ""),
        source_uuid=source_uuid,
        source_path=normalize_file_uri_to_path(filename),
        track_type=track_type,
        clip_type=int(clip_obj.get("type") or 0),
        stream_id=int(clip_obj.get("streamId") or 0),
        tl_begin_us=int(clip_obj.get("tlBegin") or 0),
        tl_end_us=int(clip_obj.get("tlEnd") or 0),
        in_point_us=int(clip_obj.get("inPoint") or 0),
        out_point_us=int(clip_obj.get("outPoint") or 0),
        volume_gain_db=volume_gain_db,
        has_transform=has_transform,
        has_crop_pan_zoom=has_crop_pan_zoom,
        effect_ids=tuple(sorted(set(effect_ids))),
        effect_params=effect_params,
        speed_reverse=speed_reverse,
        speed_non_trivial=speed_non_trivial,
        flags=tuple(sorted(set(flags))),
    )


def _parse_volume_gain(effect_obj: dict[str, Any]) -> float | None:
    param_list = effect_obj.get("paramList")
    if not isinstance(param_list, list):
        return None

    for param in param_list:
        if not isinstance(param, dict):
            continue
        if str(param.get("name")) != "VolumeGain":
            continue
        fx_param = param.get("fxParam")
        if not isinstance(fx_param, dict):
            continue
        value = fx_param.get("unValue")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _parse_effect_params(effect_obj: dict[str, Any]) -> dict[str, Any]:
    param_list = effect_obj.get("paramList")
    if not isinstance(param_list, list):
        return {}

    result: dict[str, Any] = {}
    for param in param_list:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or "")
        if not name:
            continue
        fx_param = param.get("fxParam")
        if not isinstance(fx_param, dict):
            continue
        if "unValue" in fx_param:
            result[name] = fx_param.get("unValue")

    return result


def _parse_speed_flags(speed_obj: Any) -> tuple[bool, bool]:
    if not isinstance(speed_obj, dict):
        return False, False

    reverse = bool(speed_obj.get("reverse"))
    non_trivial = reverse

    speed_param = speed_obj.get("speedParam")
    parsed_param: dict[str, Any] | None = None

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
            values: list[float] = []
            for frame in keyframes:
                if not isinstance(frame, dict):
                    continue
                value = frame.get("_value")
                try:
                    values.append(float(value))
                except (TypeError, ValueError):
                    non_trivial = True
            if any(abs(value - 1.0) > 1e-6 for value in values):
                non_trivial = True

    return reverse, non_trivial


def _has_non_empty_keyframe_param(field_obj: Any) -> bool:
    if not isinstance(field_obj, dict):
        return False
    parameter = field_obj.get("parameter")
    if not isinstance(parameter, str) or not parameter.strip():
        return False
    try:
        parsed = json.loads(parameter)
    except json.JSONDecodeError:
        return True
    keyframes = parsed.get("keyframeSets")
    return isinstance(keyframes, list) and len(keyframes) > 0


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
