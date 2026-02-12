from __future__ import annotations

from wfp_compiler.cli import build_parser


def test_render_engine_defaults_to_v2() -> None:
    parser = build_parser()
    args = parser.parse_args(["render", "--input", "in.wfp", "--output", "out.mp4"])
    assert args.engine == "v2"


def test_parity_scan_command_parses() -> None:
    parser = build_parser()
    args = parser.parse_args(["parity", "scan", "--manifest", "manifest.json"])
    assert args.command == "parity"
    assert args.parity_command == "scan"
    assert args.required_features.endswith("required_features_v2.json")


def test_parity_run_command_parses() -> None:
    parser = build_parser()
    args = parser.parse_args(["parity", "run", "--manifest", "manifest.json"])
    assert args.command == "parity"
    assert args.parity_command == "run"
    assert args.report.endswith("report.json")


def test_parity_effects_command_parses() -> None:
    parser = build_parser()
    args = parser.parse_args(["parity", "effects", "--manifest", "manifest.json"])
    assert args.command == "parity"
    assert args.parity_command == "effects"
    assert args.report.endswith("effects_report.json")
