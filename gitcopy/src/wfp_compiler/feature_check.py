from __future__ import annotations

from collections import Counter
from typing import Any

from .models import ParsedProject, Track

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
}


def analyze_project_features(project: ParsedProject) -> list[str]:
    warnings: list[str] = []

    if not project.video_tracks:
        warnings.append("Project has no video tracks (trackType=1).")

    if len(project.video_tracks) > 1:
        warnings.append(
            f"Project has {len(project.video_tracks)} video tracks. Only the first video track is rendered in v1."
        )

    for track in project.video_tracks:
        overlaps = _count_overlaps(track)
        if overlaps:
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

    if speed_non_trivial_count:
        warnings.append(
            f"Detected {speed_non_trivial_count} clip(s) with non-trivial speed data; advanced speed curves are not fully implemented."
        )
    if keyframe_flag_count:
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
