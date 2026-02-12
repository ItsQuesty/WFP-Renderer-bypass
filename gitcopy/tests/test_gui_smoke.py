from __future__ import annotations

import tkinter as tk

import pytest

from wfp_compiler.gui import WfpCompilerApp


def test_gui_smoke_instantiates_and_closes() -> None:
    try:
        app = WfpCompilerApp()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable in test environment: {exc}")
    app.update_idletasks()
    app.destroy()
