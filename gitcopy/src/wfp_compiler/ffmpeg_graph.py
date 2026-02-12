from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import RenderPlan

WFP_TICKS_PER_SECOND = 10_000_000
WFP_TICKS_PER_MILLISECOND = 10_000


@dataclass(slots=True)
class FFmpegGraph:
    input_files: list[Path]
    filter_complex: str
    video_label: str = "vout"
    audio_label: str = "aout"


def build_filter_graph(plan: RenderPlan, audio_repair: bool = False) -> FFmpegGraph:
    input_index_by_key: dict[str, int] = {}
    input_files: list[Path] = []

    def input_index(path: Path) -> int:
        key = str(path).casefold()
        if key not in input_index_by_key:
            input_index_by_key[key] = len(input_files)
            input_files.append(path)
        return input_index_by_key[key]

    lines: list[str] = []

    fps_expr = _fmt_ratio(plan.project.info.fps_num, plan.project.info.fps_den)
    width = plan.project.info.width
    height = plan.project.info.height
    duration_us = plan.project.info.timeline_duration_us
    sample_rate = plan.project.info.sample_rate

    video_link_labels: list[str] = []
    for idx, segment in enumerate(plan.video_segments):
        seg_label = f"vseg{idx}"
        video_link_labels.append(f"[{seg_label}]")

        if segment.is_gap:
            gap_duration_us = max(0, segment.tl_end_us - segment.tl_begin_us)
            lines.append(
                "color=c=black:s={width}x{height}:r={fps}:d={dur},format=yuv420p[{label}]".format(
                    width=width,
                    height=height,
                    fps=fps_expr,
                    dur=_fmt_seconds(gap_duration_us),
                    label=seg_label,
                )
            )
            continue

        assert segment.source_path is not None
        assert segment.stream_id is not None
        assert segment.in_point_us is not None
        assert segment.out_point_us is not None

        src_index = input_index(segment.source_path)
        stream_expr = f"{src_index}:v:{segment.stream_id}"
        lines.append(
            "[{src}]trim=start={src_in}:end={src_out},setpts=PTS-STARTPTS,"
            "scale={width}:{height}:force_original_aspect_ratio=decrease,"
            "pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            "fps={fps},setsar=1,format=yuv420p[{label}]".format(
                src=stream_expr,
                src_in=_fmt_seconds(segment.in_point_us),
                src_out=_fmt_seconds(segment.out_point_us),
                width=width,
                height=height,
                fps=fps_expr,
                label=seg_label,
            )
        )

    if not video_link_labels:
        raise ValueError("Render plan has no video segments.")

    lines.append(
        "{inputs}concat=n={n}:v=1:a=0[vcat]".format(inputs="".join(video_link_labels), n=len(video_link_labels))
    )
    lines.append(
        "[vcat]trim=duration={duration},setpts=PTS-STARTPTS[vout]".format(
            duration=_fmt_seconds(duration_us),
        )
    )

    audio_link_labels: list[str] = []
    for idx, segment in enumerate(plan.audio_segments):
        seg_label = f"aseg{idx}"
        audio_link_labels.append(f"[{seg_label}]")

        src_index = input_index(segment.source_path)
        stream_expr = f"{src_index}:a:{segment.stream_id}"
        delay_ms = max(0, round(segment.tl_begin_us / WFP_TICKS_PER_MILLISECOND))

        lines.append(
            "[{src}]atrim=start={src_in}:end={src_out},asetpts=PTS-STARTPTS,"
            "aresample={sample_rate},volume={gain}dB,adelay={delay}:all=1[{label}]".format(
                src=stream_expr,
                src_in=_fmt_seconds(segment.in_point_us),
                src_out=_fmt_seconds(segment.out_point_us),
                sample_rate=sample_rate,
                gain=_fmt_float(segment.volume_gain_db),
                delay=delay_ms,
                label=seg_label,
            )
        )

    if audio_link_labels:
        audio_tail = "atrim=duration={duration},asetpts=PTS-STARTPTS".format(
            duration=_fmt_seconds(duration_us),
        )
        if audio_repair:
            audio_tail += "," + _audio_repair_filters()
        lines.append(
            "{inputs}amix=inputs={n}:normalize=0:dropout_transition=0,"
            "{audio_tail}[aout]".format(
                inputs="".join(audio_link_labels),
                n=len(audio_link_labels),
                audio_tail=audio_tail,
            )
        )
    else:
        null_chain = "anullsrc=r={sample_rate}:cl=stereo,atrim=duration={duration}".format(
            sample_rate=sample_rate,
            duration=_fmt_seconds(duration_us),
        )
        if audio_repair:
            null_chain += "," + _audio_repair_filters()
        lines.append(f"{null_chain}[aout]")

    return FFmpegGraph(input_files=input_files, filter_complex=";".join(lines))


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


def _audio_repair_filters() -> str:
    # Balanced speech-focused cleanup:
    # - highpass reduces low-frequency plosive thumps
    # - dynaudnorm evens spoken volume with minimal allowed gain-up (g=3)
    # - acompressor + alimiter catch spikes with unity makeup (makeup=1)
    # - final slight attenuation avoids post-repair overs
    return (
        "highpass=f=100,"
        "dynaudnorm=f=120:g=3:p=0.85:m=12:s=5,"
        "acompressor=threshold=-24dB:ratio=3:attack=7:release=170:makeup=1,"
        "alimiter=limit=0.92:level=disabled,"
        "volume=0.95"
    )
