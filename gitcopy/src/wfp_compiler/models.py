from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class QualityPreset(str, Enum):
    LOW = "Low"
    BALANCED = "Balanced"
    HIGH = "High"


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
    flags: tuple[str, ...] = field(default_factory=tuple)

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


@dataclass(slots=True)
class ParsedProject:
    wfp_path: Path
    info: ProjectInfo
    tracks: list[Track]
    resources_by_uuid: dict[str, ResourceInfo]
    parser_warnings: list[str] = field(default_factory=list)

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
class RenderResult:
    success: bool
    output_path: Path
    encoder: str | None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
