from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ffmpeg_runtime import FFmpegNotFoundError, resolve_ffmpeg_binaries
from .gui import launch_gui
from .models import QualityPreset
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
    render.add_argument("--ffmpeg", help="Explicit ffmpeg executable path")
    render.add_argument("--ffprobe", help="Explicit ffprobe executable path")

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


if __name__ == "__main__":
    raise SystemExit(main())
