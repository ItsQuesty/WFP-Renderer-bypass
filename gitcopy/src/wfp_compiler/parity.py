from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ffmpeg_runtime import FFmpegBinaries, resolve_ffmpeg_binaries
from .models import QualityPreset, RenderEngine
from .parser import parse_wfp_project
from .renderer import render_project_to_mp4
from .timeline_v2 import build_timeline_v2


@dataclass(slots=True)
class CorpusCase:
    name: str
    input_wfp: Path
    golden_output: Path
    output_name: str


def scan_corpus_features(
    manifest_path: str | Path,
    required_features_path: str | Path = "parity/required_features_v2.json",
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)

    effect_counter: Counter[str] = Counter()
    transition_counter: Counter[str] = Counter()
    title_counter: Counter[str] = Counter()
    color_counter: Counter[str] = Counter()

    for case in manifest:
        project = parse_wfp_project(case.input_wfp)
        timeline = build_timeline_v2(project)

        for layer in timeline.layered_video_clips:
            for effect_id in layer.clip.effect_ids:
                effect_counter[effect_id] += 1
        for transition in timeline.transitions:
            transition_counter[transition.kind] += 1
        for title in timeline.title_layers:
            title_counter["text/title"] += 1
            if title.font_size is not None:
                title_counter["text/font-size"] += 1
            if title.color is not None:
                title_counter["text/color"] += 1
        for adjustments in timeline.color_adjustments_by_clip.values():
            for adjustment in adjustments:
                color_counter[adjustment.effect_id] += 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_count": len(manifest),
        "selection_policy": "top cumulative 95%, excluding ai/stabilization",
        "required": {
            "effects": _select_top_cumulative(effect_counter),
            "transitions": _select_top_cumulative(transition_counter),
            "titles": _select_top_cumulative(title_counter),
            "color": _select_top_cumulative(color_counter),
        },
        "counts": {
            "effects": dict(effect_counter),
            "transitions": dict(transition_counter),
            "titles": dict(title_counter),
            "color": dict(color_counter),
        },
    }
    output = Path(required_features_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def run_parity_suite(
    manifest_path: str | Path,
    report_path: str | Path = "parity/report.json",
    ffmpeg_binaries: FFmpegBinaries | None = None,
    quality: QualityPreset = QualityPreset.BALANCED,
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    binaries = ffmpeg_binaries or resolve_ffmpeg_binaries()

    case_reports: list[dict[str, Any]] = []
    pass_count = 0
    with tempfile.TemporaryDirectory(prefix="wfp_parity_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        for case in manifest:
            render_output = tmp_root / case.output_name
            project = parse_wfp_project(case.input_wfp)
            result = render_project_to_mp4(
                project=project,
                output_path=render_output,
                quality=quality,
                ffmpeg_binaries=binaries,
                engine=RenderEngine.V2,
                audio_repair=True,
            )

            case_entry: dict[str, Any] = {
                "name": case.name,
                "input_wfp": str(case.input_wfp),
                "golden_output": str(case.golden_output),
                "render_success": result.success,
                "warnings": result.warnings,
                "error": result.error,
                "metrics": {},
                "category": "bug",
                "pass": False,
            }
            if not result.success or not render_output.exists():
                case_entry["category"] = _categorize_failure(result.warnings, render_failed=True)
                case_reports.append(case_entry)
                continue
            if not case.golden_output.exists():
                case_entry["category"] = "corpus_anomaly"
                case_entry["error"] = "Golden output file missing."
                case_reports.append(case_entry)
                continue

            exact_match = _sha256(render_output) == _sha256(case.golden_output)
            metrics = _compare_outputs(binaries, render_output, case.golden_output)
            case_entry["metrics"] = metrics
            case_entry["exact_match"] = exact_match
            case_pass = exact_match or _passes_thresholds(metrics)
            case_entry["pass"] = case_pass
            if case_pass:
                case_entry["category"] = "pass"
                pass_count += 1
            else:
                case_entry["category"] = _categorize_failure(result.warnings, render_failed=False)
            case_reports.append(case_entry)

    total = len(case_reports)
    pass_rate = (pass_count / total) if total else 0.0
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_count": total,
        "pass_count": pass_count,
        "pass_rate": pass_rate,
        "suite_pass": pass_rate >= 0.95,
        "thresholds": {
            "duration_delta_seconds_max": 0.1,
            "ssim_min": 0.97,
            "psnr_min": 40.0,
            "audio_mean_volume_delta_db_max": 2.0,
        },
        "cases": case_reports,
    }
    output = Path(report_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def run_effect_coverage(
    manifest_path: str | Path,
    report_path: str | Path = "parity/effects_report.json",
    ffmpeg_binaries: FFmpegBinaries | None = None,
    quality: QualityPreset = QualityPreset.BALANCED,
    engine: RenderEngine | str = RenderEngine.V2,
    max_cases_per_effect: int | None = None,
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    binaries = ffmpeg_binaries or resolve_ffmpeg_binaries()
    selected_engine = _normalize_engine(engine)

    effect_to_cases: dict[str, list[CorpusCase]] = {}
    for case in manifest:
        project = parse_wfp_project(case.input_wfp)
        timeline = build_timeline_v2(project)
        seen_effects: set[str] = set()
        for layer in timeline.layered_video_clips:
            for effect_id in layer.clip.effect_ids:
                seen_effects.add(effect_id)
        for effect_id in sorted(seen_effects):
            effect_to_cases.setdefault(effect_id, []).append(case)

    per_effect: list[dict[str, Any]] = []
    effects_passed = 0
    with tempfile.TemporaryDirectory(prefix="wfp_effects_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        for effect_id, cases in sorted(effect_to_cases.items()):
            selected_cases = cases
            if max_cases_per_effect is not None and max_cases_per_effect > 0:
                selected_cases = cases[:max_cases_per_effect]

            case_reports: list[dict[str, Any]] = []
            effect_pass = True
            for case in selected_cases:
                output_name = f"{_slug(effect_id)}__{case.output_name}"
                render_output = tmp_root / output_name
                project = parse_wfp_project(case.input_wfp)
                result = render_project_to_mp4(
                    project=project,
                    output_path=render_output,
                    quality=quality,
                    ffmpeg_binaries=binaries,
                    engine=selected_engine,
                    audio_repair=True,
                )
                case_ok = bool(result.success and render_output.exists())
                if not case_ok:
                    effect_pass = False
                case_reports.append(
                    {
                        "case_name": case.name,
                        "input_wfp": str(case.input_wfp),
                        "output_file": str(render_output),
                        "pass": case_ok,
                        "error": result.error,
                        "warnings": result.warnings,
                    }
                )

            if effect_pass:
                effects_passed += 1
            per_effect.append(
                {
                    "effect_id": effect_id,
                    "case_count": len(selected_cases),
                    "pass": effect_pass,
                    "cases": case_reports,
                }
            )

    total_effects = len(per_effect)
    coverage_rate = (effects_passed / total_effects) if total_effects else 0.0
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": selected_engine.value,
        "manifest_count": len(manifest),
        "effect_count": total_effects,
        "effects_passed": effects_passed,
        "coverage_rate": coverage_rate,
        "suite_pass": total_effects > 0 and coverage_rate >= 0.95,
        "effects": per_effect,
    }
    output = Path(report_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _load_manifest(manifest_path: str | Path) -> list[CorpusCase]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("Manifest must contain a non-empty 'cases' array.")

    result: list[CorpusCase] = []
    for index, item in enumerate(cases):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or f"case-{index}")
        input_wfp = Path(str(item.get("input_wfp") or "")).expanduser()
        golden = Path(str(item.get("golden_output") or "")).expanduser()
        output_name = str(item.get("output_name") or f"{name}.mp4")
        if not input_wfp:
            continue
        result.append(CorpusCase(name=name, input_wfp=input_wfp, golden_output=golden, output_name=output_name))
    if not result:
        raise RuntimeError("No valid cases in manifest.")
    return result


def _select_top_cumulative(counter: Counter[str], ratio: float = 0.95) -> list[dict[str, Any]]:
    if not counter:
        return []
    total = sum(counter.values())
    running = 0
    selected: list[dict[str, Any]] = []
    for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
        running += count
        selected.append(
            {
                "name": key,
                "count": count,
                "coverage": running / total,
            }
        )
        if running / total >= ratio:
            break
    return selected


def _compare_outputs(binaries: FFmpegBinaries, rendered: Path, golden: Path) -> dict[str, float]:
    duration_a = _probe_duration_seconds(binaries, rendered)
    duration_b = _probe_duration_seconds(binaries, golden)
    ssim = _probe_ssim(binaries, rendered, golden)
    psnr = _probe_psnr(binaries, rendered, golden)
    mean_volume_a = _probe_mean_volume_db(binaries, rendered)
    mean_volume_b = _probe_mean_volume_db(binaries, golden)
    return {
        "duration_delta_seconds": abs(duration_a - duration_b),
        "ssim": ssim,
        "psnr": psnr,
        "audio_mean_volume_delta_db": abs(mean_volume_a - mean_volume_b),
    }


def _passes_thresholds(metrics: dict[str, float]) -> bool:
    return (
        metrics.get("duration_delta_seconds", 999.0) <= 0.1
        and metrics.get("ssim", 0.0) >= 0.97
        and metrics.get("psnr", 0.0) >= 40.0
        and metrics.get("audio_mean_volume_delta_db", 999.0) <= 2.0
    )


def _probe_duration_seconds(binaries: FFmpegBinaries, path: Path) -> float:
    command = [
        str(binaries.ffprobe_path),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return 0.0
    payload = json.loads(proc.stdout or "{}")
    try:
        return float(payload.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _probe_ssim(binaries: FFmpegBinaries, rendered: Path, golden: Path) -> float:
    command = [
        str(binaries.ffmpeg_path),
        "-hide_banner",
        "-i",
        str(rendered),
        "-i",
        str(golden),
        "-lavfi",
        "ssim",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    return _parse_float(proc.stderr, r"All:(\d+\.\d+)")


def _probe_psnr(binaries: FFmpegBinaries, rendered: Path, golden: Path) -> float:
    command = [
        str(binaries.ffmpeg_path),
        "-hide_banner",
        "-i",
        str(rendered),
        "-i",
        str(golden),
        "-lavfi",
        "psnr",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    return _parse_float(proc.stderr, r"average:(\d+\.\d+)")


def _probe_mean_volume_db(binaries: FFmpegBinaries, path: Path) -> float:
    command = [
        str(binaries.ffmpeg_path),
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    return _parse_float(proc.stderr, r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def _parse_float(text: str, pattern: str) -> float:
    matches = re.findall(pattern, text or "")
    if not matches:
        return 0.0
    try:
        return float(matches[-1])
    except (TypeError, ValueError):
        return 0.0


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _categorize_failure(warnings: list[str], render_failed: bool) -> str:
    if render_failed:
        return "bug"
    lowered = "\n".join(warnings).casefold()
    if "ai effects are not implemented" in lowered or "stabilization is not implemented" in lowered:
        return "unsupported_out_of_scope"
    if "unknown/unsupported effect" in lowered:
        return "unsupported_in_scope"
    return "bug"


def _normalize_engine(engine: RenderEngine | str) -> RenderEngine:
    if isinstance(engine, RenderEngine):
        return engine
    try:
        return RenderEngine(str(engine).lower())
    except ValueError:
        return RenderEngine.V2


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_")
    return cleaned or "effect"
