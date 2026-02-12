from __future__ import annotations

import threading
from pathlib import Path

from wfp_compiler.ffmpeg_graph import FFmpegGraph
from wfp_compiler.ffmpeg_runtime import FFmpegBinaries
from wfp_compiler import renderer


def test_run_ffmpeg_once_uses_filter_complex_script_for_long_graph(tmp_path: Path, monkeypatch) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"x")
    ffprobe.write_bytes(b"x")
    binaries = FFmpegBinaries(ffmpeg, ffprobe)

    captured: dict[str, object] = {}

    class _FakeProcess:
        def __init__(self, command: list[str]) -> None:
            self.command = command
            self.stderr = []
            self.returncode = 0

        def poll(self) -> int:
            return 0

    def fake_popen(command, **_kwargs):
        captured["command"] = command
        return _FakeProcess(command)

    monkeypatch.setattr(renderer.subprocess, "Popen", fake_popen)

    graph = FFmpegGraph(input_files=[], filter_complex=("a" * 7000))
    success, _error = renderer._run_ffmpeg_once(
        binaries=binaries,
        graph=graph,
        output_path=tmp_path / "out.mp4",
        encoder="libx264",
        video_bitrate="8M",
        audio_bitrate="160k",
        log_callback=None,
        cancel_event=threading.Event(),
    )

    assert success is True
    command = captured["command"]
    assert isinstance(command, list)
    assert "-filter_complex_script" in command
    script_index = command.index("-filter_complex_script") + 1
    script_path = Path(command[script_index])
    assert not script_path.exists()


def test_run_ffmpeg_once_returns_error_when_spawn_fails(tmp_path: Path, monkeypatch) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"x")
    ffprobe.write_bytes(b"x")
    binaries = FFmpegBinaries(ffmpeg, ffprobe)

    def fake_popen(_command, **_kwargs):
        raise OSError("CreateProcess failed")

    monkeypatch.setattr(renderer.subprocess, "Popen", fake_popen)

    graph = FFmpegGraph(input_files=[], filter_complex="anull[aout];color[cv]")
    success, error = renderer._run_ffmpeg_once(
        binaries=binaries,
        graph=graph,
        output_path=tmp_path / "out.mp4",
        encoder="libx264",
        video_bitrate="8M",
        audio_bitrate="160k",
        log_callback=None,
        cancel_event=threading.Event(),
    )

    assert success is False
    assert isinstance(error, str)
    assert "Failed to start ffmpeg process" in error
