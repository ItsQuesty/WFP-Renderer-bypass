from __future__ import annotations

import json
from pathlib import Path

from wfp_compiler.ffmpeg_runtime import FFmpegBinaries
from wfp_compiler.models import RenderResult
from wfp_compiler.parity import run_effect_coverage, scan_corpus_features

from .helpers import create_minimal_wfp


def test_parity_scan_writes_required_features(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    wfp = tmp_path / "scan_case.wfp"
    create_minimal_wfp(wfp, media, include_color_effect=True, extra_video_clip_fields={"text": "Title"})

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "name": "scan_case",
                        "input_wfp": str(wfp),
                        "golden_output": str(tmp_path / "golden.mp4"),
                        "output_name": "scan_case.mp4",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    required_path = tmp_path / "required.json"
    payload = scan_corpus_features(manifest, required_path)

    assert required_path.exists()
    assert payload["manifest_count"] == 1
    assert "required" in payload


def test_effect_coverage_generates_report(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    wfp = tmp_path / "effects_case.wfp"
    create_minimal_wfp(wfp, media, include_color_effect=True)

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "name": "effects_case",
                        "input_wfp": str(wfp),
                        "golden_output": str(tmp_path / "golden.mp4"),
                        "output_name": "effects_case.mp4",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_render(**kwargs):
        output = Path(kwargs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mp4")
        return RenderResult(success=True, output_path=output, encoder="libx264", warnings=[])

    monkeypatch.setattr("wfp_compiler.parity.render_project_to_mp4", fake_render)

    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"x")
    ffprobe.write_bytes(b"x")

    report_path = tmp_path / "effects_report.json"
    report = run_effect_coverage(
        manifest_path=manifest,
        report_path=report_path,
        ffmpeg_binaries=FFmpegBinaries(ffmpeg, ffprobe),
    )

    assert report_path.exists()
    assert report["effect_count"] > 0
    assert report["suite_pass"] is True
