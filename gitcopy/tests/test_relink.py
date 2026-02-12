from __future__ import annotations

from pathlib import Path

from wfp_compiler.parser import parse_wfp_project
from wfp_compiler.relink import auto_match_missing_files, coerce_relink_map, find_missing_media

from .helpers import create_minimal_wfp


def test_relink_missing_media_and_auto_match(tmp_path: Path) -> None:
    missing_source = tmp_path / "missing_source.mp4"
    wfp = tmp_path / "missing.wfp"
    create_minimal_wfp(wfp, missing_source)

    project = parse_wfp_project(wfp)
    missing = find_missing_media(project)
    assert missing == [missing_source]

    search_root = tmp_path / "search"
    search_root.mkdir()
    replacement = search_root / "missing_source.mp4"
    replacement.write_bytes(b"fake")

    matched = auto_match_missing_files(missing, search_root)
    relink_map = coerce_relink_map({str(k): str(v) for k, v in matched.items()})

    assert relink_map
    assert not find_missing_media(project, relink_map)
