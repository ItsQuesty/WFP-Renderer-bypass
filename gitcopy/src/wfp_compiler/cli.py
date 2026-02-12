from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ffmpeg_runtime import FFmpegNotFoundError, resolve_ffmpeg_binaries
from .gui import launch_gui
from .models import QualityPreset, RenderEngine
from .parity import run_effect_coverage, run_parity_suite, scan_corpus_features
from .parser import WfpParseError, parse_wfp_project
from .renderer import normalize_output_path, render_project_to_mp4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wfp-compiler", description="Render Filmora .wfp projects to MP4")
    subparsers = parser.add_subparsers(dest="command")

    render = subparsers.add_parser("render", help="Render one .wfp project to MP4")
    render.add_argument("--input", required=True, help="Path to input .wfp file")
    render.add_argument("--output", required=True, help="Path to output .mp4")
    render.add_argument(
        "--quality",
        choices=[preset.value for preset in QualityPreset],
        default=QualityPreset.BALANCED.value,
        help="Output quality preset",
    )
    render.add_argument(
        "--audio-repair",
        dest="audio_repair",
        action="store_true",
        help="Apply speech-focused audio cleanup and leveling during export (default)",
    )
    render.add_argument(
        "--no-audio-repair",
        dest="audio_repair",
        action="store_false",
        help="Disable audio repair processing",
    )
    render.set_defaults(audio_repair=True)
    render.add_argument(
        "--engine",
        choices=[engine.value for engine in RenderEngine],
        default=RenderEngine.V2.value,
        help="Rendering engine to use",
    )
    render.add_argument("--ffmpeg", help="Explicit ffmpeg executable path")
    render.add_argument("--ffprobe", help="Explicit ffprobe executable path")

    parity = subparsers.add_parser("parity", help="Parity tooling")
    parity_sub = parity.add_subparsers(dest="parity_command", required=True)

    scan = parity_sub.add_parser("scan", help="Scan corpus and generate required feature map")
    scan.add_argument("--manifest", required=True, help="Path to corpus manifest JSON")
    scan.add_argument(
        "--required-features",
        default="parity/required_features_v2.json",
        help="Output path for required feature map JSON",
    )

    run = parity_sub.add_parser("run", help="Run parity suite against golden outputs")
    run.add_argument("--manifest", required=True, help="Path to corpus manifest JSON")
    run.add_argument("--report", default="parity/report.json", help="Output path for parity report JSON")
    run.add_argument(
        "--quality",
        choices=[preset.value for preset in QualityPreset],
        default=QualityPreset.BALANCED.value,
        help="Render quality for parity runs",
    )
    run.add_argument("--ffmpeg", help="Explicit ffmpeg executable path")
    run.add_argument("--ffprobe", help="Explicit ffprobe executable path")

    effects = parity_sub.add_parser("effects", help="Auto-test discovered effects across corpus")
    effects.add_argument("--manifest", required=True, help="Path to corpus manifest JSON")
    effects.add_argument("--report", default="parity/effects_report.json", help="Output path for effect coverage report")
    effects.add_argument(
        "--quality",
        choices=[preset.value for preset in QualityPreset],
        default=QualityPreset.BALANCED.value,
        help="Render quality for effect coverage runs",
    )
    effects.add_argument(
        "--engine",
        choices=[engine.value for engine in RenderEngine],
        default=RenderEngine.V2.value,
        help="Rendering engine to use for effect coverage",
    )
    effects.add_argument(
        "--max-cases-per-effect",
        type=int,
        default=0,
        help="Optional limit on case samples per effect (0 means no limit)",
    )
    effects.add_argument("--ffmpeg", help="Explicit ffmpeg executable path")
    effects.add_argument("--ffprobe", help="Explicit ffprobe executable path")

    subparsers.add_parser("gui", help="Launch desktop GUI")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "gui"):
        launch_gui()
        return 0

    if args.command == "render":
        return _handle_render(args)
    if args.command == "parity":
        return _handle_parity(args)

    parser.print_help()
    return 2


def _handle_render(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_path = normalize_output_path(args.output)

    try:
        project = parse_wfp_project(input_path)
    except WfpParseError as exc:
        print(f"Parse error: {exc}", file=sys.stderr)
        return 1

    try:
        binaries = resolve_ffmpeg_binaries(args.ffmpeg, args.ffprobe)
    except FFmpegNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    def _log(line: str) -> None:
        print(line)

    result = render_project_to_mp4(
        project=project,
        output_path=output_path,
        quality=args.quality,
        ffmpeg_binaries=binaries,
        audio_repair=bool(args.audio_repair),
        log_callback=_log,
        engine=args.engine,
    )

    if result.warnings:
        print("Compatibility warnings:")
        for warning in result.warnings:
            print(f"- {warning}")

    if not result.success:
        print(f"Export failed: {result.error}", file=sys.stderr)
        return 1

    print(f"Export completed: {result.output_path}")
    if result.encoder:
        print(f"Encoder used: {result.encoder}")
    return 0


def _handle_parity(args: argparse.Namespace) -> int:
    if args.parity_command == "scan":
        payload = scan_corpus_features(args.manifest, args.required_features)
        print(f"Feature scan complete: {args.required_features}")
        print(f"Cases scanned: {payload['manifest_count']}")
        return 0

    if args.parity_command == "run":
        try:
            binaries = resolve_ffmpeg_binaries(args.ffmpeg, args.ffprobe)
        except FFmpegNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        report = run_parity_suite(
            manifest_path=args.manifest,
            report_path=args.report,
            ffmpeg_binaries=binaries,
            quality=QualityPreset(args.quality),
        )
        print(f"Parity run complete: {args.report}")
        print(f"Pass rate: {report['pass_rate']:.2%} ({report['pass_count']}/{report['manifest_count']})")
        if not report["suite_pass"]:
            print("Suite failed 95% gate.", file=sys.stderr)
            return 1
        return 0
    if args.parity_command == "effects":
        try:
            binaries = resolve_ffmpeg_binaries(args.ffmpeg, args.ffprobe)
        except FFmpegNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        limit = None if int(args.max_cases_per_effect) <= 0 else int(args.max_cases_per_effect)
        report = run_effect_coverage(
            manifest_path=args.manifest,
            report_path=args.report,
            ffmpeg_binaries=binaries,
            quality=QualityPreset(args.quality),
            engine=args.engine,
            max_cases_per_effect=limit,
        )
        print(f"Effect coverage run complete: {args.report}")
        print(
            f"Effects passed: {report['effects_passed']}/{report['effect_count']} "
            f"({report['coverage_rate']:.2%})"
        )
        if not report["suite_pass"]:
            print("Effect coverage suite failed 95% gate.", file=sys.stderr)
            return 1
        return 0

    print("Unknown parity command.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
