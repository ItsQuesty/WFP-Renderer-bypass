from __future__ import annotations

import math
from pathlib import Path

from .ffmpeg_graph import FFmpegGraph, WFP_TICKS_PER_MILLISECOND, WFP_TICKS_PER_SECOND
from .models import Clip, RenderPlanV2, TitleLayer


def build_filter_graph_v2(plan: RenderPlanV2, audio_repair: bool = False) -> FFmpegGraph:
    timeline = plan.timeline
    project = timeline.project.info
    fps_expr = _fmt_ratio(project.fps_num, project.fps_den)
    width = project.width
    height = project.height
    duration_us = project.timeline_duration_us
    sample_rate = project.sample_rate

    input_index_by_key: dict[str, int] = {}
    input_files: list[Path] = []

    def input_index(path: Path) -> int:
        key = str(path).casefold()
        if key not in input_index_by_key:
            input_index_by_key[key] = len(input_files)
            input_files.append(path)
        return input_index_by_key[key]

    lines: list[str] = []

    video_boundaries = _collect_video_boundaries(plan, duration_us)
    video_interval_labels: list[str] = []
    for idx, (start_us, end_us) in enumerate(zip(video_boundaries, video_boundaries[1:])):
        if end_us <= start_us:
            continue
        interval_label = f"vint{idx}"
        video_interval_labels.append(f"[{interval_label}]")

        active_layers = [
            item
            for item in timeline.layered_video_clips
            if item.clip.tl_begin_us < end_us and item.clip.tl_end_us > start_us
        ]
        active_layers.sort(key=lambda item: item.z_index)
        if not active_layers:
            lines.append(
                "color=c=black:s={width}x{height}:r={fps}:d={dur},format=yuv420p[{label}]".format(
                    width=width,
                    height=height,
                    fps=fps_expr,
                    dur=_fmt_seconds(end_us - start_us),
                    label=interval_label,
                )
            )
            continue

        composed_label: str | None = None
        for layer_idx, layer in enumerate(active_layers):
            clip = layer.clip
            stream_expr = f"{input_index(clip.source_path)}:v:{clip.stream_id}"
            source_start_s, source_end_s = _map_timeline_interval_to_source(clip, start_us, end_us)
            source_len_s = max(1e-6, source_end_s - source_start_s)
            interval_len_s = max(1e-6, (end_us - start_us) / WFP_TICKS_PER_SECOND)
            setpts_factor = interval_len_s / source_len_s
            clip_label = f"vint{idx}l{layer_idx}"

            chain = [
                "[{src}]trim=start={src_start}:end={src_end}".format(
                    src=stream_expr,
                    src_start=_fmt_float(source_start_s),
                    src_end=_fmt_float(source_end_s),
                ),
                "setpts=PTS-STARTPTS",
            ]
            if clip.speed_reverse:
                chain.append("reverse")
            chain.append(f"setpts=PTS*{_fmt_float(setpts_factor)}")
            color_filter = _color_filter_for_clip(plan, clip)
            if color_filter:
                chain.append(color_filter)
            chain.extend(
                [
                    "scale={width}:{height}:force_original_aspect_ratio=decrease".format(width=width, height=height),
                    "pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black".format(width=width, height=height),
                    f"fps={fps_expr}",
                    "setsar=1",
                    "format=rgba" if layer_idx > 0 else "format=yuv420p",
                ]
            )
            lines.append(",".join(chain) + f"[{clip_label}]")

            if composed_label is None:
                composed_label = clip_label
                continue

            overlay_out = f"vint{idx}o{layer_idx}"
            lines.append(
                "[{base}][{top}]overlay=shortest=1:eof_action=pass[{out}]".format(
                    base=composed_label,
                    top=clip_label,
                    out=overlay_out,
                )
            )
            composed_label = overlay_out

        assert composed_label is not None
        title_out = _apply_titles_for_interval(lines, timeline.title_layers, composed_label, idx, start_us, end_us)
        final_video = title_out or composed_label
        lines.append(f"[{final_video}]format=yuv420p[{interval_label}]")

    if video_interval_labels:
        lines.append(
            "{inputs}concat=n={n}:v=1:a=0[vtmp]".format(inputs="".join(video_interval_labels), n=len(video_interval_labels))
        )
        lines.append("[vtmp]trim=duration={duration},setpts=PTS-STARTPTS[vout]".format(duration=_fmt_seconds(duration_us)))
    else:
        lines.append(
            "color=c=black:s={width}x{height}:r={fps}:d={dur},format=yuv420p[vout]".format(
                width=width,
                height=height,
                fps=fps_expr,
                dur=_fmt_seconds(duration_us),
            )
        )

    audio_boundaries = _collect_audio_boundaries(plan, duration_us)
    audio_interval_labels: list[str] = []
    for idx, (start_us, end_us) in enumerate(zip(audio_boundaries, audio_boundaries[1:])):
        if end_us <= start_us:
            continue
        interval_label = f"aint{idx}"
        audio_interval_labels.append(f"[{interval_label}]")

        active_audio = [clip for clip in timeline.audio_clips if clip.tl_begin_us < end_us and clip.tl_end_us > start_us]
        if not active_audio:
            lines.append(
                "anullsrc=r={sample_rate}:cl=stereo,atrim=duration={dur},asetpts=PTS-STARTPTS[{label}]".format(
                    sample_rate=sample_rate,
                    dur=_fmt_seconds(end_us - start_us),
                    label=interval_label,
                )
            )
            continue

        part_labels: list[str] = []
        for clip_idx, clip in enumerate(active_audio):
            source_start_s, source_end_s = _map_timeline_interval_to_source(clip, start_us, end_us)
            source_len_s = max(1e-6, source_end_s - source_start_s)
            interval_len_s = max(1e-6, (end_us - start_us) / WFP_TICKS_PER_SECOND)
            atempo = source_len_s / interval_len_s
            label = f"aint{idx}c{clip_idx}"
            part_labels.append(f"[{label}]")

            local_mid_s = max(
                0.0,
                min(
                    (clip.tl_end_us - clip.tl_begin_us) / WFP_TICKS_PER_SECOND,
                    ((start_us + end_us) / 2 - clip.tl_begin_us) / WFP_TICKS_PER_SECOND,
                ),
            )
            gain_db = (
                float(clip.volume_gain_db or 0.0)
                + _interpolate_curve_value(clip.volume_keyframes, local_mid_s, default=0.0)
                + _ducking_to_db(_interpolate_curve_value(clip.ducking_keyframes, local_mid_s, default=0.0))
            )

            chain_parts = [
                "[{src}]atrim=start={src_start}:end={src_end}".format(
                    src=f"{input_index(clip.source_path)}:a:{clip.stream_id}",
                    src_start=_fmt_float(source_start_s),
                    src_end=_fmt_float(source_end_s),
                ),
                "asetpts=PTS-STARTPTS",
            ]
            if clip.speed_reverse:
                chain_parts.append("areverse")
            chain_parts.append(_build_atempo_chain(atempo))
            chain_parts.append(f"aresample={sample_rate}")
            chain_parts.append(f"volume={_fmt_float(gain_db)}dB")
            chain_parts.append("atrim=duration={dur}".format(dur=_fmt_seconds(end_us - start_us)))
            chain_parts.append("asetpts=PTS-STARTPTS")
            lines.append(",".join(chain_parts) + f"[{label}]")

        if len(part_labels) == 1:
            lines.append(f"{part_labels[0]}anull[{interval_label}]")
        else:
            lines.append(
                "{parts}amix=inputs={count}:normalize=0:dropout_transition=0,atrim=duration={dur},asetpts=PTS-STARTPTS[{label}]".format(
                    parts="".join(part_labels),
                    count=len(part_labels),
                    dur=_fmt_seconds(end_us - start_us),
                    label=interval_label,
                )
            )

    if audio_interval_labels:
        lines.append("{inputs}concat=n={n}:v=0:a=1[atmp]".format(inputs="".join(audio_interval_labels), n=len(audio_interval_labels)))
        audio_tail = "atrim=duration={duration},asetpts=PTS-STARTPTS".format(duration=_fmt_seconds(duration_us))
        if audio_repair:
            audio_tail += "," + _audio_repair_filters()
        lines.append(f"[atmp]{audio_tail}[aout]")
    else:
        lines.append(
            "anullsrc=r={sample_rate}:cl=stereo,atrim=duration={dur},asetpts=PTS-STARTPTS[aout]".format(
                sample_rate=sample_rate,
                dur=_fmt_seconds(duration_us),
            )
        )

    return FFmpegGraph(input_files=input_files, filter_complex=";".join(lines))


def _collect_video_boundaries(plan: RenderPlanV2, duration_us: int) -> list[int]:
    boundaries: set[int] = {0, max(0, duration_us)}
    for layer in plan.timeline.layered_video_clips:
        clip = layer.clip
        boundaries.add(max(0, clip.tl_begin_us))
        boundaries.add(max(0, clip.tl_end_us))
        for time_s, _value in clip.speed_keyframes:
            boundaries.add(max(0, clip.tl_begin_us + int(time_s * WFP_TICKS_PER_SECOND)))
    for title in plan.timeline.title_layers:
        boundaries.add(max(0, title.tl_begin_us))
        boundaries.add(max(0, title.tl_end_us))
    return sorted(boundaries)


def _collect_audio_boundaries(plan: RenderPlanV2, duration_us: int) -> list[int]:
    boundaries: set[int] = {0, max(0, duration_us)}
    for clip in plan.timeline.audio_clips:
        boundaries.add(max(0, clip.tl_begin_us))
        boundaries.add(max(0, clip.tl_end_us))
        for time_s, _value in clip.speed_keyframes:
            boundaries.add(max(0, clip.tl_begin_us + int(time_s * WFP_TICKS_PER_SECOND)))
        for time_s, _value in clip.volume_keyframes:
            boundaries.add(max(0, clip.tl_begin_us + int(time_s * WFP_TICKS_PER_SECOND)))
        for time_s, _value in clip.ducking_keyframes:
            boundaries.add(max(0, clip.tl_begin_us + int(time_s * WFP_TICKS_PER_SECOND)))
    return sorted(boundaries)


def _map_timeline_interval_to_source(clip: Clip, start_us: int, end_us: int) -> tuple[float, float]:
    local_start_s = max(0.0, (start_us - clip.tl_begin_us) / WFP_TICKS_PER_SECOND)
    local_end_s = max(0.0, (end_us - clip.tl_begin_us) / WFP_TICKS_PER_SECOND)
    local_start_s, local_end_s = sorted((local_start_s, local_end_s))

    clip_duration_s = max(1e-6, (clip.tl_end_us - clip.tl_begin_us) / WFP_TICKS_PER_SECOND)
    speed_points = _speed_points_for_clip(clip, clip_duration_s)
    progress_start_s = _integrate_speed_curve(speed_points, local_start_s)
    progress_end_s = _integrate_speed_curve(speed_points, local_end_s)

    in_s = clip.in_point_us / WFP_TICKS_PER_SECOND
    out_s = clip.out_point_us / WFP_TICKS_PER_SECOND
    if clip.speed_reverse:
        src_start = out_s - progress_end_s
        src_end = out_s - progress_start_s
    else:
        src_start = in_s + progress_start_s
        src_end = in_s + progress_end_s

    src_start = max(in_s, min(out_s, src_start))
    src_end = max(in_s, min(out_s, src_end))
    if src_end < src_start:
        src_start, src_end = src_end, src_start
    if math.isclose(src_start, src_end):
        src_end = min(out_s, src_start + 1.0 / 120.0)
    return src_start, src_end


def _speed_points_for_clip(clip: Clip, clip_duration_s: float) -> list[tuple[float, float]]:
    if not clip.speed_keyframes:
        return [(0.0, 1.0), (clip_duration_s, 1.0)]

    points = sorted((max(0.0, t), max(0.05, float(v))) for t, v in clip.speed_keyframes)
    if not points:
        return [(0.0, 1.0), (clip_duration_s, 1.0)]
    if points[0][0] > 0.0:
        points.insert(0, (0.0, points[0][1]))
    if points[-1][0] < clip_duration_s:
        points.append((clip_duration_s, points[-1][1]))

    normalized: list[tuple[float, float]] = []
    for time_s, value in points:
        clamped_t = min(clip_duration_s, max(0.0, time_s))
        if normalized and math.isclose(normalized[-1][0], clamped_t):
            normalized[-1] = (clamped_t, value)
            continue
        normalized.append((clamped_t, value))
    if len(normalized) == 1:
        normalized.append((clip_duration_s, normalized[0][1]))
    return normalized


def _integrate_speed_curve(points: list[tuple[float, float]], t: float) -> float:
    if not points:
        return t
    if t <= 0.0:
        return 0.0

    total = 0.0
    capped_t = min(t, points[-1][0])
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t1 <= t0:
            continue
        if capped_t <= t0:
            break
        seg_end = min(capped_t, t1)
        dt = seg_end - t0
        slope = (v1 - v0) / (t1 - t0)
        total += v0 * dt + 0.5 * slope * dt * dt
        if seg_end >= capped_t:
            break
    if capped_t > points[-1][0]:
        total += (capped_t - points[-1][0]) * points[-1][1]
    return max(0.0, total)


def _build_atempo_chain(atempo: float) -> str:
    # FFmpeg atempo supports [0.5, 2.0] per stage. Compose if needed.
    target = max(0.01, atempo)
    if math.isclose(target, 1.0, rel_tol=1e-4):
        return "atempo=1"

    stages: list[float] = []
    while target > 2.0:
        stages.append(2.0)
        target /= 2.0
    while target < 0.5:
        stages.append(0.5)
        target /= 0.5
    stages.append(target)
    return ",".join(f"atempo={_fmt_float(stage)}" for stage in stages)


def _interpolate_curve_value(points: tuple[tuple[float, float], ...], t: float, default: float = 0.0) -> float:
    if not points:
        return default
    if t <= points[0][0]:
        return float(points[0][1])
    if t >= points[-1][0]:
        return float(points[-1][1])

    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= t <= t1:
            if math.isclose(t0, t1):
                return float(v1)
            alpha = (t - t0) / (t1 - t0)
            return float(v0 + (v1 - v0) * alpha)
    return default


def _ducking_to_db(value: float) -> float:
    # Conservative interpretation: 0=no duck, 1=strong duck (~ -12 dB)
    clamped = max(0.0, min(1.0, float(value)))
    return -12.0 * clamped


def _color_filter_for_clip(plan: RenderPlanV2, clip: Clip) -> str:
    key = clip.this_uid or ""
    adjustments = plan.timeline.color_adjustments_by_clip.get(key, [])
    if not adjustments:
        return ""

    brightness: float | None = None
    contrast: float | None = None
    saturation: float | None = None
    hue: float | None = None

    for adjustment in adjustments:
        params = {str(k).casefold(): v for k, v in adjustment.params.items()}
        if "brightness" in params:
            brightness = _normalize_brightness(_to_float(params["brightness"]))
        if "contrast" in params:
            contrast = _normalize_contrast(_to_float(params["contrast"]))
        if "saturation" in params:
            saturation = _normalize_saturation(_to_float(params["saturation"]))
        if "hue" in params:
            hue = _to_float(params["hue"])

    chain: list[str] = []
    if any(value is not None for value in (brightness, contrast, saturation)):
        chain.append(
            "eq=brightness={b}:contrast={c}:saturation={s}".format(
                b=_fmt_float(brightness if brightness is not None else 0.0),
                c=_fmt_float(contrast if contrast is not None else 1.0),
                s=_fmt_float(saturation if saturation is not None else 1.0),
            )
        )
    if hue is not None:
        chain.append(f"hue=h={_fmt_float(hue)}")
    return ",".join(chain)


def _normalize_brightness(value: float | None) -> float | None:
    if value is None:
        return None
    if abs(value) > 1.0:
        return max(-1.0, min(1.0, value / 100.0))
    return max(-1.0, min(1.0, value))


def _normalize_contrast(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 3.0:
        return max(0.1, min(3.0, value / 100.0))
    return max(0.1, min(3.0, value))


def _normalize_saturation(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 3.0:
        return max(0.0, min(3.0, value / 100.0))
    return max(0.0, min(3.0, value))


def _to_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _apply_titles_for_interval(
    lines: list[str],
    titles: list[TitleLayer],
    base_label: str,
    interval_idx: int,
    start_us: int,
    end_us: int,
) -> str | None:
    active = [title for title in titles if title.tl_begin_us < end_us and title.tl_end_us > start_us]
    if not active:
        return None

    current = base_label
    for idx, title in enumerate(active):
        out_label = f"vint{interval_idx}t{idx}"
        drawtext = _drawtext_for_title(title)
        lines.append(f"[{current}]{drawtext}[{out_label}]")
        current = out_label
    return current


def _drawtext_for_title(title: TitleLayer) -> str:
    text = _escape_drawtext(title.text)
    color = title.color or "white"
    size = title.font_size if title.font_size and title.font_size > 0 else 42
    if title.x is None:
        x_expr = "(w-text_w)/2"
    elif abs(title.x) <= 1.0:
        x_expr = f"(w-text_w)*{_fmt_float(title.x)}"
    else:
        x_expr = _fmt_float(title.x)

    if title.y is None:
        y_expr = "(h-text_h)/2"
    elif abs(title.y) <= 1.0:
        y_expr = f"(h-text_h)*{_fmt_float(title.y)}"
    else:
        y_expr = _fmt_float(title.y)

    return (
        "drawtext=text='{text}':x={x}:y={y}:fontcolor={color}:fontsize={size}:"
        "box=1:boxcolor=black@0.2:boxborderw=8".format(
            text=text,
            x=x_expr,
            y=y_expr,
            color=_escape_drawtext(color),
            size=size,
        )
    )


def _escape_drawtext(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace("\n", "\\n")
    )


def _audio_repair_filters() -> str:
    return (
        "highpass=f=100,"
        "dynaudnorm=f=120:g=3:p=0.85:m=12:s=5,"
        "acompressor=threshold=-24dB:ratio=3:attack=7:release=170:makeup=1,"
        "alimiter=limit=0.92:level=disabled,"
        "volume=0.95"
    )


def _fmt_seconds(value_us: int) -> str:
    return _fmt_float(value_us / WFP_TICKS_PER_SECOND)


def _fmt_float(value: float) -> str:
    text = f"{value:.6f}"
    text = text.rstrip("0").rstrip(".")
    if text == "-0":
        return "0"
    return text or "0"


def _fmt_ratio(num: int, den: int) -> str:
    den = 1 if den == 0 else den
    return f"{num}/{den}"
