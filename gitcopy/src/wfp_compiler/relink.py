from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Mapping

from .models import Clip, ParsedProject, ResourceInfo, Track


RelinkMap = dict[str, Path]


def normalize_path_key(path: str | Path) -> str:
    value = Path(path)
    try:
        normalized = value.resolve()
    except OSError:
        normalized = value
    return str(normalized).casefold()


def coerce_relink_map(raw_map: Mapping[str, str | Path]) -> RelinkMap:
    result: RelinkMap = {}
    for original, replacement in raw_map.items():
        result[normalize_path_key(original)] = Path(replacement)
    return result


def resolve_path(path: Path, relink_map: Mapping[str, Path] | None = None) -> Path:
    if not relink_map:
        return path
    return relink_map.get(normalize_path_key(path), path)


def find_missing_media(project: ParsedProject, relink_map: Mapping[str, Path] | None = None) -> list[Path]:
    missing: dict[str, Path] = {}

    for track in project.tracks:
        for clip in track.clips:
            resolved = resolve_path(clip.source_path, relink_map)
            if not resolved.exists():
                missing[normalize_path_key(clip.source_path)] = clip.source_path

    return sorted(missing.values(), key=lambda item: str(item).casefold())


def apply_relink_map(project: ParsedProject, relink_map: Mapping[str, Path] | None) -> ParsedProject:
    if not relink_map:
        return project

    tracks: list[Track] = []
    for track in project.tracks:
        clips: list[Clip] = []
        for clip in track.clips:
            replaced_path = resolve_path(clip.source_path, relink_map)
            clips.append(replace(clip, source_path=replaced_path))
        tracks.append(replace(track, clips=clips))

    resources_by_uuid: dict[str, ResourceInfo] = {}
    for source_uuid, resource in project.resources_by_uuid.items():
        replaced_path = resolve_path(resource.path, relink_map)
        resources_by_uuid[source_uuid] = replace(resource, path=replaced_path)

    return replace(project, tracks=tracks, resources_by_uuid=resources_by_uuid)


def auto_match_missing_files(missing_paths: list[Path], base_folder: str | Path) -> RelinkMap:
    base = Path(base_folder)
    if not base.exists() or not base.is_dir():
        return {}

    by_name: dict[str, Path] = {}
    for candidate in base.rglob("*"):
        if not candidate.is_file():
            continue
        name_key = candidate.name.casefold()
        if name_key not in by_name:
            by_name[name_key] = candidate

    relinks: RelinkMap = {}
    for missing in missing_paths:
        match = by_name.get(missing.name.casefold())
        if match:
            relinks[normalize_path_key(missing)] = match

    return relinks
