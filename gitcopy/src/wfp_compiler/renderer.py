from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Mapping

from .feature_check import analyze_project_features
from .ffmpeg_graph import build_filter_graph
from .ffmpeg_runtime import (
    FFmpegBinaries,
    choose_encoder_attempt_order,
    list_available_video_encoders,
    resolve_ffmpeg_binaries,
)
from .models import AudioSegment, ParsedProject, QualityPreset, RenderPlan, RenderResult, ResourceInfo, VideoSegment
from .relink import apply_relink_map, coerce_relink_map, find_missing_media

LogCallback = Callable[[str], None]


class RenderPlanningError(RuntimeError):
    """Raised when a render plan cannot be created from a parsed project."""


class RenderCancelledError(RuntimeError):
    """Raised when the active export is canceled by the user."""


def build_render_plan(
    project: ParsedProject,
    relink_map: Mapping[str, str | Path] | None = None,
) -> RenderPlan:
    resolved_project = apply_relink_map(project, coerce_relink_map(relink_map or {}))

    warnings = analyze_project_features(resolved_project)
    missing_media = find_missing_media(resolved_project)

    video_tracks = resolved_project.video_tracks
    if not video_tracks:
        raise RenderPlanningError("No video track (trackType=1) found in project.")

    primary_video_track = sorted(video_tracks, key=lambda track: track.index)[0]
    ordered_video_clips = sorted(primary_video_track.clips, key=lambda clip: (clip.tl_begin_us, clip.tl_end_us))
    if not ordered_video_clips:
        raise RenderPlanningError("Primary video track has no clips.")

    project_duration = resolved_project.info.timeline_duration_us
    video_segments: list[VideoSegment] = []
    cursor = 0

    for clip in ordered_video_clips:
        if clip.tl_end_us <= clip.tl_begin_us:
            warnings.append(f"Skipped zero-length video clip: {clip.this_uid or clip.source_path.name}")
            continue
        if clip.out_point_us <= clip.in_point_us:
            warnings.append(f"Skipped invalid video trim range: {clip.this_uid or clip.source_path.name}")
            continue

        if clip.tl_begin_us > cursor:
            video_segments.append(
                VideoSegment(
                    tl_begin_us=cursor,
                    tl_end_us=clip.tl_begin_us,
                    source_path=None,
                    stream_id=None,
                    in_point_us=None,
                    out_point_us=None,
                )
            )

        if clip.tl_begin_us < cursor:
            warnings.append(
                "Overlapping clips found on primary video track. Rendering in timeline order without compositing overlap."
            )

        video_segments.append(
            VideoSegment(
                tl_begin_us=clip.tl_begin_us,
                tl_end_us=clip.tl_end_us,
                source_path=clip.source_path,
                stream_id=clip.stream_id,
                in_point_us=clip.in_point_us,
                out_point_us=clip.out_point_us,
            )
        )
        cursor = max(cursor, clip.tl_end_us)

    if cursor < project_duration:
        video_segments.append(
            VideoSegment(
                tl_begin_us=cursor,
                tl_end_us=project_duration,
                source_path=None,
                stream_id=None,
                in_point_us=None,
                out_point_us=None,
            )
        )

    if not video_segments:
        raise RenderPlanningError("No renderable video segments were generated.")

    audio_segments: list[AudioSegment] = []
    adjusted_audio_stream_files: set[str] = set()
    adjusted_audio_stream_count = 0
    for track in sorted(resolved_project.audio_tracks, key=lambda item: item.index):
        for clip in sorted(track.clips, key=lambda item: (item.tl_begin_us, item.tl_end_us)):
            if clip.tl_end_us <= clip.tl_begin_us:
                continue
            if clip.out_point_us <= clip.in_point_us:
                continue

            resource_info = resolved_project.resources_by_uuid.get(clip.source_uuid)
            if resource_info and resource_info.audio_stream_count == 0:
                warnings.append(
                    f"Skipped audio clip with no audio stream in resource metadata: {clip.source_path.name}"
                )
                continue

            audio_stream_index = _resolve_audio_stream_index(
                clip_stream_id=clip.stream_id,
                resource_info=resource_info,
            )
            if audio_stream_index != clip.stream_id:
                adjusted_audio_stream_count += 1
                adjusted_audio_stream_files.add(clip.source_path.name)

            audio_segments.append(
                AudioSegment(
                    tl_begin_us=clip.tl_begin_us,
                    tl_end_us=clip.tl_end_us,
                    source_path=clip.source_path,
                    stream_id=audio_stream_index,
                    in_point_us=clip.in_point_us,
                    out_point_us=clip.out_point_us,
                    volume_gain_db=clip.volume_gain_db if clip.volume_gain_db is not None else 0.0,
                )
            )

    if adjusted_audio_stream_count:
        warnings.append(
            "Adjusted audio stream index on "
            f"{adjusted_audio_stream_count} clip(s) across {len(adjusted_audio_stream_files)} file(s) "
            "(Filmora streamId -> FFmpeg audio index mapping)."
        )

    return RenderPlan(
        project=resolved_project,
        video_segments=video_segments,
        audio_segments=audio_segments,
        missing_media=missing_media,
        warnings=_dedupe_keep_order(warnings),
    )


def render_project_to_mp4(
    project: ParsedProject,
    output_path: str | Path,
    quality: QualityPreset | str = QualityPreset.BALANCED,
    ffmpeg_binaries: FFmpegBinaries | None = None,
    relink_map: Mapping[str, str | Path] | None = None,
    audio_repair: bool = False,
    log_callback: LogCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> RenderResult:
    normalized_output_path = normalize_output_path(output_path)
    plan = build_render_plan(project, relink_map=relink_map)
    if plan.missing_media:
        return RenderResult(
            success=False,
            output_path=normalized_output_path,
            encoder=None,
            warnings=plan.warnings,
            error=f"Missing media files: {', '.join(str(path) for path in plan.missing_media)}",
        )

    if audio_repair and log_callback:
        log_callback("Audio Repair enabled: de-plosive + downward leveling + spike limiting.")

    graph = build_filter_graph(plan, audio_repair=audio_repair)
    binaries = ffmpeg_binaries or resolve_ffmpeg_binaries()

    available_encoders = list_available_video_encoders(binaries)
    encoder_order = choose_encoder_attempt_order(available_encoders)
    if not encoder_order:
        return RenderResult(
            success=False,
            output_path=normalized_output_path,
            encoder=None,
            warnings=plan.warnings,
            error="No usable H.264 encoder found in ffmpeg.",
        )

    output_path = normalized_output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    settings = _quality_settings(quality)
    attempt_errors: list[str] = []

    for encoder in encoder_order:
        if log_callback:
            log_callback(f"Starting export with encoder: {encoder}")

        success, error = _run_ffmpeg_once(
            binaries=binaries,
            graph=graph,
            output_path=output_path,
            encoder=encoder,
            video_bitrate=settings["video_bitrate"],
            audio_bitrate=settings["audio_bitrate"],
            log_callback=log_callback,
            cancel_event=cancel_event,
        )

        if success:
            return RenderResult(
                success=True,
                output_path=output_path,
                encoder=encoder,
                warnings=plan.warnings,
                error=None,
            )

        if isinstance(error, RenderCancelledError):
            return RenderResult(
                success=False,
                output_path=output_path,
                encoder=encoder,
                warnings=plan.warnings,
                error="Export canceled by user.",
            )

        attempt_errors.append(f"{encoder}: {error}")
        if log_callback:
            log_callback(f"Encoder {encoder} failed. Trying fallback.")

    return RenderResult(
        success=False,
        output_path=output_path,
        encoder=None,
        warnings=plan.warnings,
        error="All encoder attempts failed. " + " | ".join(attempt_errors),
    )


def _run_ffmpeg_once(
    binaries: FFmpegBinaries,
    graph,
    output_path: Path,
    encoder: str,
    video_bitrate: str,
    audio_bitrate: str,
    log_callback: LogCallback | None,
    cancel_event: threading.Event | None,
) -> tuple[bool, str | Exception]:
    command = [
        str(binaries.ffmpeg_path),
        "-hide_banner",
        "-y",
        "-nostdin",
    ]

    for input_path in graph.input_files:
        command.extend(["-i", str(input_path)])

    command.extend(
        [
            "-filter_complex",
            graph.filter_complex,
            "-map",
            f"[{graph.video_label}]",
            "-map",
            f"[{graph.audio_label}]",
            "-c:v",
            encoder,
            "-b:v",
            video_bitrate,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-movflags",
            "+faststart",
            "-f",
            "mp4",
        ]
    )

    if encoder == "libx264":
        command.extend(["-preset", "medium"])

    command.append(str(output_path))

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    stderr_lines: list[str] = []

    def _stderr_reader() -> None:
        if process.stderr is None:
            return
        for raw_line in process.stderr:
            line = raw_line.rstrip("\n")
            stderr_lines.append(line)
            if len(stderr_lines) > 500:
                stderr_lines.pop(0)
            if log_callback:
                log_callback(line)

    reader_thread = threading.Thread(target=_stderr_reader, daemon=True)
    reader_thread.start()

    while process.poll() is None:
        if cancel_event and cancel_event.is_set():
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
            reader_thread.join(timeout=1.0)
            return False, RenderCancelledError("Canceled")
        time.sleep(0.1)

    reader_thread.join(timeout=1.0)

    if process.returncode == 0:
        return True, ""

    error_tail = "\n".join(stderr_lines[-25:])
    return False, error_tail or f"ffmpeg exited with code {process.returncode}"


def _quality_settings(quality: QualityPreset | str) -> dict[str, str]:
    if isinstance(quality, QualityPreset):
        selected = quality
    else:
        try:
            selected = QualityPreset(str(quality))
        except ValueError:
            selected = QualityPreset.BALANCED

    if selected == QualityPreset.LOW:
        return {"video_bitrate": "4M", "audio_bitrate": "128k"}
    if selected == QualityPreset.HIGH:
        return {"video_bitrate": "12M", "audio_bitrate": "192k"}
    return {"video_bitrate": "8M", "audio_bitrate": "160k"}


def normalize_output_path(output_path: str | Path) -> Path:
    path = Path(output_path)
    if path.suffix.lower() == ".mp4":
        return path
    return path.with_suffix(".mp4")


def _resolve_audio_stream_index(clip_stream_id: int, resource_info: ResourceInfo | None) -> int:
    if clip_stream_id < 0:
        return 0
    if resource_info is None:
        return clip_stream_id

    audio_count = max(0, int(resource_info.audio_stream_count))
    video_count = max(0, int(resource_info.video_stream_count))

    if audio_count <= 1:
        return 0 if clip_stream_id >= 0 else clip_stream_id

    # Filmora often stores absolute stream slot index (video first, then audio).
    if clip_stream_id >= video_count:
        candidate = clip_stream_id - video_count
        if 0 <= candidate < audio_count:
            return candidate

    if 0 <= clip_stream_id < audio_count:
        return clip_stream_id

    return 0


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered
