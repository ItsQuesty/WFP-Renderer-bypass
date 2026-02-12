from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable, Mapping

from .feature_check import analyze_project_features
from .ffmpeg_graph import build_filter_graph
from .ffmpeg_graph_v2 import build_filter_graph_v2
from .ffmpeg_runtime import (
    FFmpegBinaries,
    choose_encoder_attempt_order,
    list_available_video_encoders,
    resolve_ffmpeg_binaries,
)
from .models import (
    AudioSegment,
    Clip,
    ParsedProject,
    QualityPreset,
    RenderEngine,
    RenderPlan,
    RenderPlanV2,
    RenderResult,
    ResourceInfo,
    VideoSegment,
)
from .relink import apply_relink_map, coerce_relink_map, find_missing_media
from .timeline_v2 import build_timeline_v2

LogCallback = Callable[[str], None]


class RenderPlanningError(RuntimeError):
    """Raised when a render plan cannot be created from a parsed project."""


class RenderCancelledError(RuntimeError):
    """Raised when the active export is canceled by the user."""


def build_render_plan(
    project: ParsedProject,
    relink_map: Mapping[str, str | Path] | None = None,
    engine: RenderEngine | str = RenderEngine.V1,
) -> RenderPlan | RenderPlanV2:
    selected = _normalize_engine(engine)
    if selected == RenderEngine.V2:
        return build_render_plan_v2(project, relink_map=relink_map)
    return build_render_plan_v1(project, relink_map=relink_map)


def build_render_plan_v1(
    project: ParsedProject,
    relink_map: Mapping[str, str | Path] | None = None,
) -> RenderPlan:
    resolved_project = apply_relink_map(project, coerce_relink_map(relink_map or {}))

    warnings = analyze_project_features(resolved_project, engine=RenderEngine.V1)
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

    audio_segments = _build_audio_segments_v1(resolved_project, warnings)

    return RenderPlan(
        project=resolved_project,
        video_segments=video_segments,
        audio_segments=audio_segments,
        missing_media=missing_media,
        warnings=_dedupe_keep_order(warnings),
    )


def build_render_plan_v2(
    project: ParsedProject,
    relink_map: Mapping[str, str | Path] | None = None,
) -> RenderPlanV2:
    resolved_project = apply_relink_map(project, coerce_relink_map(relink_map or {}))
    warnings = analyze_project_features(resolved_project, engine=RenderEngine.V2)
    missing_media = find_missing_media(resolved_project)

    timeline = build_timeline_v2(resolved_project)
    if not timeline.layered_video_clips:
        raise RenderPlanningError("No renderable video clips found for v2 timeline.")

    adjusted_audio_stream_files: set[str] = set()
    adjusted_audio_stream_count = 0
    normalized_audio: list[Clip] = []
    for clip in timeline.audio_clips:
        resource_info = resolved_project.resources_by_uuid.get(clip.source_uuid)
        if resource_info and resource_info.audio_stream_count == 0:
            warnings.append(f"Skipped audio clip with no audio stream in resource metadata: {clip.source_path.name}")
            continue

        audio_stream_index = _resolve_audio_stream_index(
            clip_stream_id=clip.stream_id,
            resource_info=resource_info,
        )
        if audio_stream_index != clip.stream_id:
            adjusted_audio_stream_count += 1
            adjusted_audio_stream_files.add(clip.source_path.name)
            clip = replace(clip, stream_id=audio_stream_index)
        normalized_audio.append(clip)

    if adjusted_audio_stream_count:
        warnings.append(
            "Adjusted audio stream index on "
            f"{adjusted_audio_stream_count} clip(s) across {len(adjusted_audio_stream_files)} file(s) "
            "(Filmora streamId -> FFmpeg audio index mapping)."
        )

    timeline = replace(timeline, audio_clips=normalized_audio)
    return RenderPlanV2(timeline=timeline, missing_media=missing_media, warnings=_dedupe_keep_order(warnings))


def render_project_to_mp4(
    project: ParsedProject,
    output_path: str | Path,
    quality: QualityPreset | str = QualityPreset.BALANCED,
    ffmpeg_binaries: FFmpegBinaries | None = None,
    relink_map: Mapping[str, str | Path] | None = None,
    audio_repair: bool = False,
    log_callback: LogCallback | None = None,
    cancel_event: threading.Event | None = None,
    engine: RenderEngine | str = RenderEngine.V2,
) -> RenderResult:
    selected_engine = _normalize_engine(engine)
    normalized_output_path = normalize_output_path(output_path)
    plan = build_render_plan(project, relink_map=relink_map, engine=selected_engine)
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
    if log_callback:
        log_callback(f"Render engine: {selected_engine.value}")

    if selected_engine == RenderEngine.V2:
        assert isinstance(plan, RenderPlanV2)
        graph = build_filter_graph_v2(plan, audio_repair=audio_repair)
    else:
        assert isinstance(plan, RenderPlan)
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

    filter_script_path: Path | None = None
    filter_arg = "-filter_complex"
    filter_value = graph.filter_complex
    if _should_use_filter_script(graph.filter_complex):
        with tempfile.NamedTemporaryFile("w", suffix=".ffgraph", delete=False, encoding="utf-8") as handle:
            handle.write(graph.filter_complex)
            filter_script_path = Path(handle.name)
        filter_arg = "-filter_complex_script"
        filter_value = str(filter_script_path)

    command.extend(
        [
            filter_arg,
            filter_value,
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

    try:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                **_windows_subprocess_kwargs(),
            )
        except OSError as exc:
            return False, f"Failed to start ffmpeg process: {exc}"

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
    finally:
        if filter_script_path is not None:
            try:
                filter_script_path.unlink(missing_ok=True)
            except OSError:
                pass


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


def _build_audio_segments_v1(project: ParsedProject, warnings: list[str]) -> list[AudioSegment]:
    audio_segments: list[AudioSegment] = []
    adjusted_audio_stream_files: set[str] = set()
    adjusted_audio_stream_count = 0
    for track in sorted(project.audio_tracks, key=lambda item: item.index):
        for clip in sorted(track.clips, key=lambda item: (item.tl_begin_us, item.tl_end_us)):
            if clip.tl_end_us <= clip.tl_begin_us:
                continue
            if clip.out_point_us <= clip.in_point_us:
                continue

            resource_info = project.resources_by_uuid.get(clip.source_uuid)
            if resource_info and resource_info.audio_stream_count == 0:
                warnings.append(f"Skipped audio clip with no audio stream in resource metadata: {clip.source_path.name}")
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
    return audio_segments


def _normalize_engine(engine: RenderEngine | str) -> RenderEngine:
    if isinstance(engine, RenderEngine):
        return engine
    try:
        return RenderEngine(str(engine).lower())
    except ValueError:
        return RenderEngine.V2


def _should_use_filter_script(filter_complex: str) -> bool:
    if not filter_complex:
        return False
    # Windows has command-line length limits; large graphs can fail to spawn ffmpeg.
    if os.name == "nt" and len(filter_complex) > 6000:
        return True
    return False


def _windows_subprocess_kwargs() -> dict[str, int]:
    if os.name != "nt":
        return {}
    # Avoid flashing transient console windows for ffmpeg/ffprobe invocations.
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered
