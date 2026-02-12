from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class QualityPreset(str, Enum):
    LOW = "Low"
    BALANCED = "Balanced"
    HIGH = "High"


class RenderEngine(str, Enum):
    V1 = "v1"
    V2 = "v2"


@dataclass(slots=True)
class ProjectInfo:
    file_name: str
    timeline_media_id: str
    timeline_duration_us: int
    fps_num: int
    fps_den: int
    width: int
    height: int
    sample_rate: int
    timeline_path_in_zip: str


@dataclass(slots=True)
class ResourceInfo:
    source_uuid: str
    path: Path
    video_stream_count: int
    audio_stream_count: int
    raw_extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KeyframePoint:
    time_s: float
    value: float


@dataclass(slots=True)
class KeyframeCurve:
    points: tuple[KeyframePoint, ...] = field(default_factory=tuple)


@dataclass(slots=True)
class Clip:
    this_uid: str
    source_uuid: str
    source_path: Path
    track_type: int
    clip_type: int
    stream_id: int
    tl_begin_us: int
    tl_end_us: int
    in_point_us: int
    out_point_us: int
    volume_gain_db: float | None
    has_transform: bool
    has_crop_pan_zoom: bool
    effect_ids: tuple[str, ...] = field(default_factory=tuple)
    effect_params: dict[str, dict[str, Any]] = field(default_factory=dict)
    speed_reverse: bool = False
    speed_non_trivial: bool = False
    speed_keyframes: tuple[tuple[float, float], ...] = field(default_factory=tuple)
    volume_keyframes: tuple[tuple[float, float], ...] = field(default_factory=tuple)
    ducking_keyframes: tuple[tuple[float, float], ...] = field(default_factory=tuple)
    flags: tuple[str, ...] = field(default_factory=tuple)
    raw_extra: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_us(self) -> int:
        return max(0, self.out_point_us - self.in_point_us)


@dataclass(slots=True)
class Track:
    index: int
    track_type: int
    track_tag: int | None
    uuid: str
    clips: list[Clip]
    raw_extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedProject:
    wfp_path: Path
    info: ProjectInfo
    tracks: list[Track]
    resources_by_uuid: dict[str, ResourceInfo]
    parser_warnings: list[str] = field(default_factory=list)
    raw_extra: dict[str, Any] = field(default_factory=dict)

    @property
    def video_tracks(self) -> list[Track]:
        return [track for track in self.tracks if track.track_type == 1]

    @property
    def audio_tracks(self) -> list[Track]:
        return [track for track in self.tracks if track.track_type == 2]


@dataclass(slots=True)
class VideoSegment:
    tl_begin_us: int
    tl_end_us: int
    source_path: Path | None
    stream_id: int | None
    in_point_us: int | None
    out_point_us: int | None

    @property
    def is_gap(self) -> bool:
        return self.source_path is None


@dataclass(slots=True)
class AudioSegment:
    tl_begin_us: int
    tl_end_us: int
    source_path: Path
    stream_id: int
    in_point_us: int
    out_point_us: int
    volume_gain_db: float


@dataclass(slots=True)
class RenderPlan:
    project: ParsedProject
    video_segments: list[VideoSegment]
    audio_segments: list[AudioSegment]
    missing_media: list[Path]
    warnings: list[str]


@dataclass(slots=True)
class LayeredClip:
    clip: Clip
    track_index: int
    z_index: int


@dataclass(slots=True)
class Transition:
    kind: str
    duration_us: int
    from_clip_uid: str | None = None
    to_clip_uid: str | None = None
    raw_params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ColorAdjustment:
    effect_id: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TitleLayer:
    tl_begin_us: int
    tl_end_us: int
    text: str
    x: float | None = None
    y: float | None = None
    font_size: int | None = None
    color: str | None = None
    raw_params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TimelineV2:
    project: ParsedProject
    layered_video_clips: list[LayeredClip]
    audio_clips: list[Clip]
    transitions: list[Transition] = field(default_factory=list)
    title_layers: list[TitleLayer] = field(default_factory=list)
    color_adjustments_by_clip: dict[str, list[ColorAdjustment]] = field(default_factory=dict)
    raw_extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RenderPlanV2:
    timeline: TimelineV2
    missing_media: list[Path]
    warnings: list[str]


@dataclass(slots=True)
class RenderResult:
    success: bool
    output_path: Path
    encoder: str | None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
