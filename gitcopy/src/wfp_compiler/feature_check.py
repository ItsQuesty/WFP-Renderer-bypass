from __future__ import annotations

from collections import Counter
from typing import Any

from .models import ParsedProject, RenderEngine, Track

FULLY_IMPLEMENTED_EFFECTS = {
    "audio/effect/volume",
    "audio/effect/change_channel",
    "audio/effect/clip_volume",
    "audio/effect/ducking",
    "audio/effect/equalizer",
    "audio/effect/fade",
    "audio/effect/audio_enhancer",
    "audio/effect/speech_enhance",
    "video/effect/crop-pan-zoom",
    "video/effect/transform",
}

KNOWN_PARTIAL_EFFECTS = {
    "audio/effect/audio_enhancer",
    "audio/effect/change_channel",
    "audio/effect/clip_volume",
    "audio/effect/ducking",
    "audio/effect/equalizer",
    "audio/effect/fade",
    "audio/effect/speech_enhance",
    "video/effect/crop-pan-zoom",
    "video/effect/transform",
}


def build_feature_check_rows(
    project: ParsedProject,
    engine: RenderEngine | str = RenderEngine.V2,
) -> list[tuple[str, str, str]]:
    selected_engine = _normalize_engine(engine)
    rows: list[tuple[str, str, str]] = []

    video_track_count = len(project.video_tracks)
    overlap_count = sum(_count_overlaps(track) for track in project.video_tracks)
    speed_non_trivial_count = 0
    keyframe_flag_count = 0
    ai_flag_count = 0
    stabilization_count = 0
    missing_resource_entries = 0
    title_hint_count = 0
    color_hint_count = 0

    effect_counter: Counter[str] = Counter()
    effect_non_default_counter: Counter[str] = Counter()
    for track in project.tracks:
        for clip in track.clips:
            for effect_id in clip.effect_ids:
                effect_counter[effect_id] += 1
                params = clip.effect_params.get(effect_id, {})
                if not _effect_is_default_or_supported(effect_id, params):
                    effect_non_default_counter[effect_id] += 1

                lowered = effect_id.casefold()
                if "color" in lowered or "lut" in lowered or "hue" in lowered:
                    color_hint_count += 1

            if clip.speed_non_trivial:
                speed_non_trivial_count += 1
            if "volume_keyframes" in clip.flags or "audio_ducking_keyframes" in clip.flags:
                keyframe_flag_count += 1
            if "ai_user_data" in clip.flags:
                ai_flag_count += 1
            if "stabilization" in clip.flags:
                stabilization_count += 1
            if clip.source_uuid and clip.source_uuid not in project.resources_by_uuid:
                missing_resource_entries += 1
            if isinstance(clip.raw_extra.get("text"), str) and clip.raw_extra.get("text"):
                title_hint_count += 1
            if isinstance(clip.raw_extra.get("titleText"), str) and clip.raw_extra.get("titleText"):
                title_hint_count += 1

    if selected_engine == RenderEngine.V1:
        if video_track_count <= 1:
            rows.append(("Multi-track video", "Working", "Single-track timelines render normally in v1."))
        else:
            rows.append(
                (
                    "Multi-track video",
                    "Partial",
                    f"Detected {video_track_count} video tracks; v1 renders only the first track.",
                )
            )
        if overlap_count:
            rows.append(
                (
                    "Overlapping clips",
                    "Partial",
                    f"Detected {overlap_count} overlap(s); v1 does not fully composite overlaps.",
                )
            )
        else:
            rows.append(("Overlapping clips", "Working", "No overlapping clip ranges detected."))
    else:
        rows.append(
            (
                "Multi-track video",
                "Working",
                f"Detected {video_track_count} video track(s); v2 layered compositor is enabled.",
            )
        )
        rows.append(
            (
                "Overlapping clips",
                "Working",
                "V2 overlap compositing path is enabled."
                if overlap_count
                else "No overlapping clip ranges detected.",
            )
        )

    if speed_non_trivial_count:
        rows.append(
            (
                "Speed curves / reverse",
                "Working" if selected_engine == RenderEngine.V2 else "Partial",
                (
                    f"Detected {speed_non_trivial_count} clip(s) with non-trivial speed data; v2 maps speed curves."
                    if selected_engine == RenderEngine.V2
                    else f"Detected {speed_non_trivial_count} clip(s) with non-trivial speed data; v1 support is limited."
                ),
            )
        )
    else:
        rows.append(("Speed curves / reverse", "Working", "No non-trivial speed data detected."))

    if keyframe_flag_count:
        rows.append(
            (
                "Audio keyframes",
                "Working" if selected_engine == RenderEngine.V2 else "Partial",
                (
                    f"Detected {keyframe_flag_count} clip(s) with volume/ducking keyframes; v2 envelope handling is enabled."
                    if selected_engine == RenderEngine.V2
                    else f"Detected {keyframe_flag_count} clip(s) with keyframes; v1 keyframe support is limited."
                ),
            )
        )
    else:
        rows.append(("Audio keyframes", "Working", "No non-empty keyframe sets detected."))

    rows.append(
        (
            "Titles / text",
            "Working" if selected_engine == RenderEngine.V2 else "Partial",
            (
                f"Detected {title_hint_count} title/text clip hint(s); v2 title overlay path is enabled."
                if title_hint_count
                else "No text/title hints detected in parsed clip metadata."
            ),
        )
    )
    rows.append(
        (
            "Color controls",
            "Working" if selected_engine == RenderEngine.V2 else "Partial",
            (
                f"Detected {color_hint_count} color-effect hint(s); v2 color mapping path is enabled."
                if color_hint_count
                else "No color effect hints detected."
            ),
        )
    )

    if ai_flag_count:
        rows.append(
            (
                "AI effects",
                "Out of scope",
                f"Detected {ai_flag_count} clip(s) with AI metadata; AI effects are out of scope for v2.0.",
            )
        )
    else:
        rows.append(("AI effects", "Out of scope", "No AI metadata detected."))

    if stabilization_count:
        rows.append(
            (
                "Stabilization",
                "Out of scope",
                f"Detected {stabilization_count} clip(s) with stabilization metadata; stabilization is out of scope for v2.0.",
            )
        )
    else:
        rows.append(("Stabilization", "Out of scope", "No stabilization metadata detected."))

    if missing_resource_entries:
        rows.append(
            (
                "Resource consistency",
                "Partial",
                f"Detected {missing_resource_entries} clip(s) with sourceUuid missing from timeline resources.",
            )
        )
    else:
        rows.append(("Resource consistency", "Working", "All clip sourceUuid values were found in resources list."))

    for effect_id, count in sorted(effect_counter.items()):
        non_default_count = effect_non_default_counter.get(effect_id, 0)
        if effect_id in FULLY_IMPLEMENTED_EFFECTS and non_default_count == 0:
            status = "Working"
            detail = f"Effect found on {count} clip(s) with supported/default params."
        elif effect_id in KNOWN_PARTIAL_EFFECTS:
            status = "Partial"
            detail = f"Effect found on {count} clip(s); non-default params on {non_default_count} clip(s)."
        else:
            status = "Not supported"
            detail = f"Unknown or unsupported effect found on {count} clip(s)."
        rows.append((f"Effect: {effect_id}", status, detail))

    if not effect_counter:
        rows.append(("Effects", "Working", "No effects detected in clip metadata."))

    return rows


def analyze_project_features(project: ParsedProject, engine: RenderEngine | str = RenderEngine.V1) -> list[str]:
    selected_engine = _normalize_engine(engine)
    warnings: list[str] = []

    if not project.video_tracks:
        warnings.append("Project has no video tracks (trackType=1).")

    if selected_engine == RenderEngine.V1 and len(project.video_tracks) > 1:
        warnings.append(
            f"Project has {len(project.video_tracks)} video tracks. Only the first video track is rendered in v1."
        )

    for track in project.video_tracks:
        overlaps = _count_overlaps(track)
        if overlaps and selected_engine == RenderEngine.V1:
            warnings.append(
                f"Video track {track.index} has {overlaps} overlapping clip ranges. Overlaps are not fully composited in v1."
            )

    effect_counter: Counter[str] = Counter()
    effect_non_default_counter: Counter[str] = Counter()
    speed_non_trivial_count = 0
    keyframe_flag_count = 0
    ai_flag_count = 0
    stabilization_count = 0
    missing_resource_entries = 0

    for track in project.tracks:
        for clip in track.clips:
            for effect_id in clip.effect_ids:
                effect_counter[effect_id] += 1
                params = clip.effect_params.get(effect_id, {})
                if not _effect_is_default_or_supported(effect_id, params):
                    effect_non_default_counter[effect_id] += 1

            if clip.speed_non_trivial:
                speed_non_trivial_count += 1

            if "volume_keyframes" in clip.flags or "audio_ducking_keyframes" in clip.flags:
                keyframe_flag_count += 1
            if "ai_user_data" in clip.flags:
                ai_flag_count += 1
            if "stabilization" in clip.flags:
                stabilization_count += 1

            if clip.source_uuid and clip.source_uuid not in project.resources_by_uuid:
                missing_resource_entries += 1

    for effect_id, count in sorted(effect_counter.items()):
        if effect_id in FULLY_IMPLEMENTED_EFFECTS and effect_non_default_counter.get(effect_id, 0) == 0:
            continue
        if effect_id in KNOWN_PARTIAL_EFFECTS:
            non_default_count = effect_non_default_counter.get(effect_id, 0)
            if non_default_count:
                warnings.append(
                    f"Effect partially supported: {effect_id} "
                    f"(non-default params on {non_default_count}/{count} clips)."
                )
            continue
        warnings.append(f"Unknown/unsupported effect: {effect_id} (seen {count} clips).")

    if speed_non_trivial_count and selected_engine == RenderEngine.V1:
        warnings.append(
            f"Detected {speed_non_trivial_count} clip(s) with non-trivial speed data; advanced speed curves are not fully implemented."
        )
    if keyframe_flag_count and selected_engine == RenderEngine.V1:
        warnings.append(
            f"Detected {keyframe_flag_count} clip(s) with non-empty keyframe parameter sets; those keyframes are not fully implemented."
        )
    if ai_flag_count:
        warnings.append(
            f"Detected {ai_flag_count} clip(s) with AI-related metadata; AI effects are not implemented in v1."
        )
    if stabilization_count:
        warnings.append(
            f"Detected {stabilization_count} clip(s) with stabilization enabled; stabilization is not implemented in v1."
        )
    if missing_resource_entries:
        warnings.append(
            f"Detected {missing_resource_entries} clip(s) whose sourceUuid was not found in timeline resources."
        )

    warnings.extend(project.parser_warnings)
    return warnings


def _count_overlaps(track: Track) -> int:
    ordered = sorted(track.clips, key=lambda clip: (clip.tl_begin_us, clip.tl_end_us))
    overlaps = 0
    for left, right in zip(ordered, ordered[1:]):
        if right.tl_begin_us < left.tl_end_us:
            overlaps += 1
    return overlaps


def _effect_is_default_or_supported(effect_id: str, params: dict[str, Any]) -> bool:
    if effect_id == "audio/effect/volume":
        return True
    if effect_id in {
        "audio/effect/change_channel",
        "audio/effect/clip_volume",
        "audio/effect/ducking",
        "audio/effect/equalizer",
        "audio/effect/fade",
        "audio/effect/audio_enhancer",
        "audio/effect/speech_enhance",
        "video/effect/crop-pan-zoom",
    }:
        return len(params) == 0
    if effect_id == "video/effect/transform":
        if not params:
            return True
        # Filmora default transform encoding in observed projects.
        default_dw = params.get("dwValue") == 1186339
        default_enable = params.get("EnableTransform") in (1, True, "1", "true", "True")
        return default_dw and default_enable and len(params) <= 2
    return False


def _normalize_engine(engine: RenderEngine | str) -> RenderEngine:
    if isinstance(engine, RenderEngine):
        return engine
    try:
        return RenderEngine(str(engine).lower())
    except ValueError:
        return RenderEngine.V1
