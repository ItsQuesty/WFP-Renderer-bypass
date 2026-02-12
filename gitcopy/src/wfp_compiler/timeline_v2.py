from __future__ import annotations

from .models import (
    Clip,
    ColorAdjustment,
    LayeredClip,
    ParsedProject,
    TimelineV2,
    TitleLayer,
    Transition,
)


def build_timeline_v2(project: ParsedProject) -> TimelineV2:
    layered_video_clips: list[LayeredClip] = []
    audio_clips: list[Clip] = []
    transitions: list[Transition] = []
    titles: list[TitleLayer] = []
    color_by_clip: dict[str, list[ColorAdjustment]] = {}

    ordered_tracks = sorted(project.tracks, key=lambda track: track.index)
    for z_index, track in enumerate(ordered_tracks):
        for clip in sorted(track.clips, key=lambda item: (item.tl_begin_us, item.tl_end_us)):
            if clip.tl_end_us <= clip.tl_begin_us:
                continue
            if clip.out_point_us <= clip.in_point_us:
                continue

            if track.track_type == 1:
                layered_video_clips.append(LayeredClip(clip=clip, track_index=track.index, z_index=z_index))
                title_layer = _extract_title_layer(clip)
                if title_layer is not None:
                    titles.append(title_layer)

                color = _extract_color_adjustments(clip)
                if color:
                    color_by_clip[clip.this_uid or f"clip-{track.index}-{clip.tl_begin_us}"] = color

                transition = _extract_transition(clip)
                if transition is not None:
                    transitions.append(transition)
            elif track.track_type == 2:
                audio_clips.append(clip)

    layered_video_clips.sort(key=lambda item: (item.clip.tl_begin_us, item.z_index))
    audio_clips.sort(key=lambda item: (item.tl_begin_us, item.tl_end_us))
    transitions.sort(key=lambda item: (item.to_clip_uid or "", item.from_clip_uid or ""))

    return TimelineV2(
        project=project,
        layered_video_clips=layered_video_clips,
        audio_clips=audio_clips,
        transitions=transitions,
        title_layers=titles,
        color_adjustments_by_clip=color_by_clip,
    )


def _extract_transition(clip: Clip) -> Transition | None:
    transition_obj = clip.raw_extra.get("transitionInfo") or clip.raw_extra.get("transition")
    if not isinstance(transition_obj, dict):
        return None

    kind = str(transition_obj.get("id") or transition_obj.get("name") or "transition").strip()
    if not kind:
        return None
    duration_us = int(transition_obj.get("duration") or transition_obj.get("durationUs") or 0)
    if duration_us <= 0:
        return None

    return Transition(
        kind=kind,
        duration_us=duration_us,
        from_clip_uid=str(transition_obj.get("fromClip") or "") or None,
        to_clip_uid=str(transition_obj.get("toClip") or "") or None,
        raw_params={key: value for key, value in transition_obj.items()},
    )


def _extract_title_layer(clip: Clip) -> TitleLayer | None:
    if clip.track_type != 1:
        return None

    text = ""
    source = clip.raw_extra.get("text") or clip.raw_extra.get("titleText")
    if isinstance(source, str):
        text = source.strip()
    if not text:
        user_data = clip.raw_extra.get("userData") or clip.raw_extra.get("userdata")
        if isinstance(user_data, list):
            for item in user_data:
                if not isinstance(item, dict):
                    continue
                maybe_text = item.get("text") or item.get("titleText")
                if isinstance(maybe_text, str) and maybe_text.strip():
                    text = maybe_text.strip()
                    break
    if not text:
        return None

    font_size = _to_int(clip.raw_extra.get("fontSize"))
    x = _to_float(clip.raw_extra.get("x"))
    y = _to_float(clip.raw_extra.get("y"))
    color = clip.raw_extra.get("color")
    if color is not None and not isinstance(color, str):
        color = str(color)

    return TitleLayer(
        tl_begin_us=clip.tl_begin_us,
        tl_end_us=clip.tl_end_us,
        text=text,
        x=x,
        y=y,
        font_size=font_size,
        color=color,
        raw_params={key: value for key, value in clip.raw_extra.items()},
    )


def _extract_color_adjustments(clip: Clip) -> list[ColorAdjustment]:
    result: list[ColorAdjustment] = []
    for effect_id, params in clip.effect_params.items():
        lowered = effect_id.casefold()
        if "color" in lowered or "lut" in lowered or "hue" in lowered:
            result.append(ColorAdjustment(effect_id=effect_id, params=params))
            continue
        if any(key.casefold() in {"brightness", "contrast", "saturation", "hue"} for key in params):
            result.append(ColorAdjustment(effect_id=effect_id, params=params))
    return result


def _to_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _to_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
