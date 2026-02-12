from __future__ import annotations

from datetime import datetime
import json
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .ffmpeg_runtime import FFmpegNotFoundError, resolve_ffmpeg_binaries
from .models import ParsedProject, QualityPreset
from .parser import WfpParseError, parse_wfp_project
from .relink import auto_match_missing_files, find_missing_media, normalize_path_key, resolve_path
from .renderer import normalize_output_path, render_project_to_mp4


class WfpCompilerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("WFP Compiler")
        self.geometry("1360x860")
        self.minsize(1080, 680)

        self.parsed_project: ParsedProject | None = None
        self.relink_map: dict[str, Path] = {}
        self.export_thread: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self._clock_job: str | None = None

        self.project_path_var = tk.StringVar(value="")
        self.output_path_var = tk.StringVar(value="")
        self.quality_var = tk.StringVar(value=QualityPreset.BALANCED.value)
        self.audio_repair_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready. Open a .wfp project to begin.")
        self.clock_var = tk.StringVar(value="--:--:--")
        self.runtime_stats_var = tk.StringVar(value="Idle")
        self.project_meta_var = tk.StringVar(value="No project loaded.")

        self._apply_professional_theme()
        self._build_ui()
        if not self._ensure_risk_acknowledged():
            self.after(0, self.destroy)
            return
        self._tick_clock()

    def _apply_professional_theme(self) -> None:
        self.colors = {
            "bg": "#F4F6FA",
            "surface": "#FFFFFF",
            "surface_alt": "#F8FAFD",
            "border": "#D9DFEA",
            "text": "#1F2937",
            "muted": "#6B7280",
            "accent": "#2563EB",
            "accent_hover": "#1D4ED8",
            "focus": "#60A5FA",
            "warning": "#B45309",
            "danger": "#B42318",
            "text_on_accent": "#FFFFFF",
        }
        self.fonts = {
            "main": ("Segoe UI", 10),
            "main_bold": ("Segoe UI Semibold", 10),
            "title": ("Segoe UI Semibold", 18),
            "mono": ("Consolas", 10),
        }

        self.configure(bg=self.colors["bg"])
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(
            ".",
            background=self.colors["bg"],
            foreground=self.colors["text"],
            font=self.fonts["main"],
        )
        style.configure("Root.TFrame", background=self.colors["bg"])
        style.configure("Card.TFrame", background=self.colors["surface"])
        style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["text"])
        style.configure("Title.TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=self.fonts["title"])
        style.configure(
            "Subtitle.TLabel",
            background=self.colors["bg"],
            foreground=self.colors["muted"],
            font=self.fonts["main"],
        )
        style.configure(
            "Section.TLabel",
            background=self.colors["bg"],
            foreground=self.colors["muted"],
            font=self.fonts["main_bold"],
        )
        style.configure(
            "Status.TLabel",
            background=self.colors["surface_alt"],
            foreground=self.colors["text"],
            font=self.fonts["main"],
        )
        style.configure(
            "Data.TLabel",
            background=self.colors["surface"],
            foreground=self.colors["text"],
            font=self.fonts["main"],
        )
        style.configure(
            "MutedData.TLabel",
            background=self.colors["surface"],
            foreground=self.colors["muted"],
            font=self.fonts["mono"],
        )

        style.configure(
            "Card.TLabelframe",
            background=self.colors["surface"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=self.colors["surface"],
            foreground=self.colors["text"],
            font=self.fonts["main_bold"],
        )

        style.configure(
            "Primary.TButton",
            background=self.colors["accent"],
            foreground=self.colors["text_on_accent"],
            bordercolor=self.colors["accent"],
            lightcolor=self.colors["accent"],
            darkcolor=self.colors["accent"],
            padding=(12, 7),
            font=self.fonts["main_bold"],
        )
        style.map(
            "Primary.TButton",
            background=[("active", self.colors["accent_hover"]), ("pressed", self.colors["accent_hover"])],
            bordercolor=[("active", self.colors["accent_hover"])],
            foreground=[("disabled", "#D6E4FF"), ("!disabled", self.colors["text_on_accent"])],
        )

        style.configure(
            "Secondary.TButton",
            background=self.colors["surface"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            padding=(12, 7),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", self.colors["surface_alt"]), ("pressed", self.colors["surface_alt"])],
            bordercolor=[("active", self.colors["focus"])],
        )

        style.configure(
            "TEntry",
            fieldbackground=self.colors["surface"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            insertcolor=self.colors["text"],
            padding=(8, 6),
        )
        style.map("TEntry", bordercolor=[("focus", self.colors["focus"])], lightcolor=[("focus", self.colors["focus"])])

        style.configure(
            "TCombobox",
            fieldbackground=self.colors["surface"],
            foreground=self.colors["text"],
            background=self.colors["surface"],
            arrowcolor=self.colors["text"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            padding=(8, 5),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.colors["surface"])],
            bordercolor=[("focus", self.colors["focus"])],
        )
        style.configure("TCheckbutton", background=self.colors["bg"], foreground=self.colors["text"])
        style.map("TCheckbutton", foreground=[("disabled", self.colors["muted"])])

        style.configure(
            "TNotebook",
            background=self.colors["bg"],
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "TNotebook.Tab",
            background=self.colors["surface_alt"],
            foreground=self.colors["muted"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["border"],
            darkcolor=self.colors["border"],
            padding=(12, 7),
            font=self.fonts["main_bold"],
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.colors["surface"]), ("active", self.colors["surface"])],
            foreground=[("selected", self.colors["text"]), ("active", self.colors["text"])],
        )

        style.configure(
            "Treeview",
            background=self.colors["surface"],
            fieldbackground=self.colors["surface"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            rowheight=26,
            font=self.fonts["main"],
        )
        style.map(
            "Treeview",
            background=[("selected", "#DDEAFE")],
            foreground=[("selected", self.colors["text"])],
        )
        style.configure(
            "Treeview.Heading",
            background=self.colors["surface_alt"],
            foreground=self.colors["text"],
            bordercolor=self.colors["border"],
            relief="flat",
            font=self.fonts["main_bold"],
        )
        style.map("Treeview.Heading", background=[("active", "#EEF3FF")])

        style.configure(
            "TProgressbar",
            troughcolor=self.colors["surface_alt"],
            background=self.colors["accent"],
            bordercolor=self.colors["border"],
            lightcolor=self.colors["accent"],
            darkcolor=self.colors["accent"],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=self.colors["surface"],
            troughcolor=self.colors["surface_alt"],
            bordercolor=self.colors["border"],
            arrowcolor=self.colors["muted"],
        )

        self.option_add("*TCombobox*Listbox.background", self.colors["surface"])
        self.option_add("*TCombobox*Listbox.foreground", self.colors["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", "#DDEAFE")
        self.option_add("*TCombobox*Listbox.selectForeground", self.colors["text"])

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="Root.TFrame", padding=(14, 14, 14, 10))
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        header = ttk.Frame(root, style="Root.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="WFP Compiler", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Filmora .wfp to MP4 renderer",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Label(header, textvariable=self.clock_var, style="Subtitle.TLabel").grid(row=0, column=1, sticky="e")

        settings = ttk.LabelFrame(root, text="Project Settings", style="Card.TLabelframe", padding=(12, 10, 12, 10))
        settings.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(2, weight=0)

        ttk.Label(settings, text="Project", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(settings, textvariable=self.project_path_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.open_project_button = ttk.Button(
            settings,
            text="Open .wfp",
            command=self.open_project,
            style="Secondary.TButton",
        )
        self.open_project_button.grid(row=0, column=2, sticky="ew")

        ttk.Label(settings, text="Output", style="Section.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(settings, textvariable=self.output_path_var).grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
        ttk.Button(
            settings,
            text="Browse",
            command=self.choose_output_path,
            style="Secondary.TButton",
        ).grid(row=1, column=2, sticky="ew", pady=(8, 0))

        ttk.Label(settings, text="Quality", style="Section.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        quality_row = ttk.Frame(settings, style="Root.TFrame")
        quality_row.grid(row=2, column=1, columnspan=2, sticky="w", pady=(8, 0))
        quality_combo = ttk.Combobox(
            quality_row,
            textvariable=self.quality_var,
            values=[preset.value for preset in QualityPreset],
            state="readonly",
            width=16,
        )
        quality_combo.grid(row=0, column=0, sticky="w")
        quality_combo.current(1)
        ttk.Checkbutton(
            quality_row,
            text="Audio Repair (Recommended)",
            variable=self.audio_repair_var,
        ).grid(row=0, column=1, sticky="w", padx=(14, 0))

        action_row = ttk.Frame(settings, style="Root.TFrame")
        action_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        action_row.columnconfigure(2, weight=1)

        self.export_button = ttk.Button(action_row, text="Export", command=self.start_export, style="Primary.TButton")
        self.export_button.grid(row=0, column=0, sticky="w")

        self.cancel_button = ttk.Button(
            action_row,
            text="Cancel",
            command=self.cancel_export,
            state="disabled",
            style="Secondary.TButton",
        )
        self.cancel_button.grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.progress = ttk.Progressbar(action_row, mode="indeterminate")
        self.progress.grid(row=0, column=2, sticky="ew", padx=(12, 0))

        body = ttk.Panedwindow(root, orient=tk.HORIZONTAL)
        body.grid(row=2, column=0, sticky="nsew")

        side_card = ttk.LabelFrame(body, text="Session Overview", style="Card.TLabelframe", padding=(12, 12, 12, 12))
        side_card.columnconfigure(0, weight=1)
        side_card.rowconfigure(4, weight=1)
        body.add(side_card, weight=1)

        ttk.Label(side_card, text="STATUS", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            side_card,
            textvariable=self.status_var,
            style="Data.TLabel",
            wraplength=290,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(4, 12))

        ttk.Label(side_card, text="RUNTIME", style="Section.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Label(
            side_card,
            textvariable=self.runtime_stats_var,
            style="MutedData.TLabel",
            justify="left",
        ).grid(row=3, column=0, sticky="ew", pady=(4, 12))

        ttk.Label(side_card, text="PROJECT", style="Section.TLabel").grid(row=4, column=0, sticky="nw")
        ttk.Label(
            side_card,
            textvariable=self.project_meta_var,
            style="MutedData.TLabel",
            justify="left",
            wraplength=290,
        ).grid(row=5, column=0, sticky="nsew", pady=(4, 0))

        main_panel = ttk.Frame(body, style="Root.TFrame")
        main_panel.columnconfigure(0, weight=1)
        main_panel.rowconfigure(0, weight=1)
        body.add(main_panel, weight=4)

        tabs = ttk.Notebook(main_panel)
        tabs.grid(row=0, column=0, sticky="nsew", padx=(10, 0))

        warnings_tab = ttk.Frame(tabs, style="Root.TFrame")
        warnings_tab.columnconfigure(0, weight=1)
        warnings_tab.rowconfigure(0, weight=1)
        tabs.add(warnings_tab, text="Compatibility")

        warning_frame = ttk.LabelFrame(
            warnings_tab,
            text="Compatibility Warnings",
            style="Card.TLabelframe",
            padding=(10, 10, 10, 10),
        )
        warning_frame.grid(row=0, column=0, sticky="nsew")
        warning_frame.columnconfigure(0, weight=1)
        warning_frame.rowconfigure(0, weight=1)
        self.warning_text = tk.Text(warning_frame, height=12, wrap="word")
        self.warning_text.grid(row=0, column=0, sticky="nsew")
        self.warning_text.configure(
            bg=self.colors["surface"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            selectbackground="#DDEAFE",
            selectforeground=self.colors["text"],
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=self.fonts["mono"],
            padx=8,
            pady=8,
        )
        warning_scroll = ttk.Scrollbar(warning_frame, orient="vertical", command=self.warning_text.yview)
        warning_scroll.grid(row=0, column=1, sticky="ns")
        self.warning_text.configure(yscrollcommand=warning_scroll.set, state="disabled")
        relink_tab = ttk.Frame(tabs, style="Root.TFrame")
        relink_tab.columnconfigure(0, weight=1)
        relink_tab.rowconfigure(0, weight=1)
        tabs.add(relink_tab, text="Media Relink")

        missing_frame = ttk.LabelFrame(
            relink_tab,
            text="Missing Media",
            style="Card.TLabelframe",
            padding=(10, 10, 10, 10),
        )
        missing_frame.grid(row=0, column=0, sticky="nsew")
        missing_frame.columnconfigure(0, weight=1)
        missing_frame.rowconfigure(0, weight=1)

        columns = ("original", "replacement", "status")
        self.media_tree = ttk.Treeview(missing_frame, columns=columns, show="headings")
        self.media_tree.heading("original", text="Original Path")
        self.media_tree.heading("replacement", text="Replacement Path")
        self.media_tree.heading("status", text="Status")
        self.media_tree.column("original", width=380, anchor="w")
        self.media_tree.column("replacement", width=380, anchor="w")
        self.media_tree.column("status", width=120, anchor="center")
        self.media_tree.grid(row=0, column=0, sticky="nsew")

        media_scroll = ttk.Scrollbar(missing_frame, orient="vertical", command=self.media_tree.yview)
        media_scroll.grid(row=0, column=1, sticky="ns")
        self.media_tree.configure(yscrollcommand=media_scroll.set)

        media_buttons = ttk.Frame(missing_frame, style="Root.TFrame")
        media_buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(media_buttons, text="Relink Selected", command=self.relink_selected, style="Secondary.TButton").pack(
            side=tk.LEFT
        )
        ttk.Button(media_buttons, text="Auto-Match Folder", command=self.auto_match_folder, style="Secondary.TButton").pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(media_buttons, text="Clear Relinks", command=self.clear_relinks, style="Secondary.TButton").pack(
            side=tk.LEFT, padx=(8, 0)
        )

        log_tab = ttk.Frame(tabs, style="Root.TFrame")
        log_tab.columnconfigure(0, weight=1)
        log_tab.rowconfigure(0, weight=1)
        tabs.add(log_tab, text="Render Log")

        log_frame = ttk.LabelFrame(log_tab, text="FFmpeg Output", style="Card.TLabelframe", padding=(10, 10, 10, 10))
        log_frame.grid(row=0, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=14, wrap="none")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(
            bg=self.colors["surface"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            selectbackground="#DDEAFE",
            selectforeground=self.colors["text"],
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=self.fonts["mono"],
            padx=8,
            pady=8,
        )
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set, state="disabled")

        status_bar = ttk.Frame(root, style="Card.TFrame", padding=(10, 7))
        status_bar.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        status_bar.columnconfigure(0, weight=1)
        ttk.Label(status_bar, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")

    def _tick_clock(self) -> None:
        self.clock_var.set(datetime.now().strftime("%H:%M:%S"))

        export_state = "Running" if self.export_thread and self.export_thread.is_alive() else "Idle"
        thread_count = threading.active_count()
        self.runtime_stats_var.set(
            f"Export: {export_state}\nThreads: {thread_count}\nAudio Repair: {'On' if self.audio_repair_var.get() else 'Off'}"
        )
        self._clock_job = self.after(1000, self._tick_clock)

    def destroy(self) -> None:
        if self._clock_job is not None:
            try:
                self.after_cancel(self._clock_job)
            except tk.TclError:
                pass
            self._clock_job = None
        super().destroy()

    def _risk_ack_path(self) -> Path:
        appdata = Path(os.getenv("APPDATA", str(Path.home())))
        settings_dir = appdata / "wfp-compiler"
        settings_dir.mkdir(parents=True, exist_ok=True)
        return settings_dir / "risk_ack.json"

    def _has_risk_ack(self) -> bool:
        if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("WFP_COMPILER_SKIP_RISK_ACK") == "1":
            return True
        path = self._risk_ack_path()
        if not path.exists():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return bool(payload.get("accepted"))
        except (json.JSONDecodeError, OSError):
            return False

    def _store_risk_ack(self) -> None:
        payload = {"accepted": True, "accepted_at": datetime.now().isoformat(timespec="seconds")}
        self._risk_ack_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _ensure_risk_acknowledged(self) -> bool:
        if self._has_risk_ack():
            return True

        accepted = tk.BooleanVar(value=False)
        decision = {"ok": False}

        dialog = tk.Toplevel(self)
        dialog.title("Risk Notice")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg=self.colors["bg"])
        dialog.resizable(False, False)
        dialog.geometry("780x460")

        container = ttk.Frame(dialog, style="Root.TFrame", padding=16)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        ttk.Label(container, text="Important Legal and Usage Notice", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 10)
        )

        warning = tk.Text(container, height=12, wrap="word")
        warning.grid(row=1, column=0, sticky="nsew")
        warning.configure(
            bg=self.colors["surface"],
            fg=self.colors["text"],
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=self.colors["danger"],
            highlightcolor=self.colors["danger"],
            font=self.fonts["main"],
            padx=10,
            pady=10,
        )
        warning.insert(
            "1.0",
            (
                "This renderer is unofficial and is not affiliated with Wondershare/Filmora.\n\n"
                "Exports may differ from Filmora output and can bypass Filmora watermark behavior.\n\n"
                "You are responsible for ensuring you have legal rights and permission to render the project "
                "content in your jurisdiction.\n\n"
                "By clicking 'I Accept Risk', you acknowledge and accept full responsibility for use."
            ),
        )
        warning.configure(state="disabled")

        ttk.Checkbutton(
            container,
            text="I accept risk and responsibility",
            variable=accepted,
        ).grid(row=2, column=0, sticky="w", pady=(12, 8))

        buttons = ttk.Frame(container, style="Root.TFrame")
        buttons.grid(row=3, column=0, sticky="e")

        def on_accept() -> None:
            if not accepted.get():
                messagebox.showerror(
                    "Acknowledgement Required",
                    "Please tick 'I accept risk and responsibility' before continuing.",
                    parent=dialog,
                )
                return
            decision["ok"] = True
            try:
                self._store_risk_ack()
            except OSError:
                pass
            dialog.destroy()

        def on_exit() -> None:
            decision["ok"] = False
            dialog.destroy()

        ttk.Button(buttons, text="Exit", command=on_exit, style="Secondary.TButton").pack(side=tk.RIGHT)
        ttk.Button(buttons, text="I Accept Risk", command=on_accept, style="Primary.TButton").pack(
            side=tk.RIGHT,
            padx=(0, 8),
        )

        dialog.protocol("WM_DELETE_WINDOW", on_exit)
        self.wait_window(dialog)
        return bool(decision["ok"])
    def open_project(self) -> None:
        chosen = filedialog.askopenfilename(filetypes=[("Filmora Project", "*.wfp"), ("All Files", "*.*")])
        if not chosen:
            return

        try:
            project = parse_wfp_project(chosen)
        except WfpParseError as exc:
            messagebox.showerror("Parse Error", str(exc), parent=self)
            return

        self.parsed_project = project
        self.relink_map.clear()
        self.project_path_var.set(str(project.wfp_path))
        default_output = self._default_output_for_project(project.wfp_path)
        self.output_path_var.set(str(default_output))
        self._refresh_warnings()
        self._refresh_media_tree()
        self._refresh_project_meta()
        self.status_var.set(f"Loaded project: {project.info.file_name}")

    def _refresh_project_meta(self) -> None:
        if not self.parsed_project:
            self.project_meta_var.set("No project loaded.")
            return

        info = self.parsed_project.info
        fps = info.fps_num / info.fps_den if info.fps_den else 0.0
        duration_sec = info.timeline_duration_us / 1_000_000
        self.project_meta_var.set(
            "\n".join(
                [
                    f"File: {info.file_name}",
                    f"Resolution: {info.width}x{info.height}",
                    f"FPS: {fps:.3f}",
                    f"Duration: {duration_sec:.2f}s",
                    f"Video tracks: {len(self.parsed_project.video_tracks)}",
                    f"Audio tracks: {len(self.parsed_project.audio_tracks)}",
                ]
            )
        )

    def _default_output_for_project(self, wfp_path: Path) -> Path:
        return wfp_path.with_name(f"{wfp_path.stem}_ripped.mp4")

    def choose_output_path(self) -> None:
        initial = self.output_path_var.get().strip()
        if not initial and self.parsed_project:
            initial = str(self._default_output_for_project(self.parsed_project.wfp_path))
        if not initial:
            initial = "output_ripped.mp4"
        initial_path = Path(initial)
        initialdir = str(initial_path.parent) if initial_path.parent and initial_path.parent.exists() else str(Path.home())
        chosen = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4 Video", "*.mp4")],
            initialfile=initial_path.name,
            initialdir=initialdir,
        )
        if chosen:
            self.output_path_var.set(chosen)

    def _refresh_warnings(self) -> None:
        self.warning_text.configure(state="normal")
        self.warning_text.delete("1.0", tk.END)

        if not self.parsed_project:
            self.warning_text.insert(tk.END, "No project loaded.")
            self.warning_text.configure(state="disabled")
            return

        from .feature_check import analyze_project_features

        warnings = analyze_project_features(self.parsed_project)
        if warnings:
            for warning in warnings:
                self.warning_text.insert(tk.END, f"- {warning}\n")
        else:
            self.warning_text.insert(tk.END, "No compatibility warnings detected.")

        self.warning_text.configure(state="disabled")

    def _refresh_media_tree(self) -> None:
        for item in self.media_tree.get_children():
            self.media_tree.delete(item)

        if not self.parsed_project:
            return

        unique_sources = sorted(
            {clip.source_path for track in self.parsed_project.tracks for clip in track.clips},
            key=lambda path: str(path).casefold(),
        )

        for source in unique_sources:
            replacement = resolve_path(source, self.relink_map)
            exists = replacement.exists()
            status = "OK" if exists else "Missing"
            self.media_tree.insert(
                "",
                tk.END,
                iid=normalize_path_key(source),
                values=(str(source), str(replacement) if replacement != source else "", status),
            )

    def relink_selected(self) -> None:
        selection = self.media_tree.selection()
        if not selection:
            return

        item = selection[0]
        values = self.media_tree.item(item, "values")
        if not values:
            return

        original = Path(values[0])
        chosen = filedialog.askopenfilename(
            title=f"Relink {original.name}",
            initialfile=original.name,
            initialdir=str(original.parent) if original.parent.exists() else str(Path.home()),
        )
        if not chosen:
            return

        self.relink_map[normalize_path_key(original)] = Path(chosen)
        self._refresh_media_tree()
        self.status_var.set(f"Relinked: {original.name}")

    def auto_match_folder(self) -> None:
        if not self.parsed_project:
            return

        missing = find_missing_media(self.parsed_project, self.relink_map)
        if not missing:
            messagebox.showinfo("Relink", "No missing media files detected.", parent=self)
            return

        folder = filedialog.askdirectory(title="Choose folder to scan for missing files")
        if not folder:
            return

        matched = auto_match_missing_files(missing, folder)
        if not matched:
            messagebox.showinfo("Relink", "No filename matches found in selected folder.", parent=self)
            return

        self.relink_map.update(matched)
        self._refresh_media_tree()
        self.status_var.set(f"Auto-matched {len(matched)} file(s).")

    def clear_relinks(self) -> None:
        self.relink_map.clear()
        self._refresh_media_tree()
        self.status_var.set("Cleared relink mappings.")

    def start_export(self) -> None:
        if self.export_thread and self.export_thread.is_alive():
            return
        if not self.parsed_project:
            messagebox.showerror("Export", "Load a project first.", parent=self)
            return

        raw_output_path = self.output_path_var.get().strip()
        if not raw_output_path:
            messagebox.showerror("Export", "Choose an output path.", parent=self)
            return
        output_path = normalize_output_path(raw_output_path)
        self.output_path_var.set(str(output_path))

        missing = find_missing_media(self.parsed_project, self.relink_map)
        if missing:
            messagebox.showerror(
                "Missing Media",
                "Resolve missing files before exporting:\n" + "\n".join(str(path) for path in missing[:12]),
                parent=self,
            )
            return

        if output_path.exists():
            overwrite = messagebox.askyesno(
                "Overwrite Output",
                f"{output_path} already exists. Overwrite it?",
                parent=self,
            )
            if not overwrite:
                return

        try:
            binaries = resolve_ffmpeg_binaries()
        except FFmpegNotFoundError as exc:
            messagebox.showerror("FFmpeg Not Found", str(exc), parent=self)
            return

        self.cancel_event.clear()
        self._set_busy(True)
        self._clear_log()
        self.status_var.set("Exporting...")

        quality = self.quality_var.get()
        audio_repair = bool(self.audio_repair_var.get())
        self.export_thread = threading.Thread(
            target=self._run_export_worker,
            args=(output_path, quality, audio_repair, binaries),
            daemon=True,
        )
        self.export_thread.start()

    def _run_export_worker(self, output_path: Path, quality: str, audio_repair: bool, binaries) -> None:
        def _log(line: str) -> None:
            self.after(0, self._append_log, line)

        result = render_project_to_mp4(
            project=self.parsed_project,
            output_path=output_path,
            quality=quality,
            ffmpeg_binaries=binaries,
            relink_map=self.relink_map,
            audio_repair=audio_repair,
            log_callback=_log,
            cancel_event=self.cancel_event,
        )
        self.after(0, self._on_export_complete, result)

    def _on_export_complete(self, result) -> None:
        self._set_busy(False)

        if result.success:
            self.status_var.set("Export completed.")
            messagebox.showinfo(
                "Export Complete",
                f"Output: {result.output_path}\nEncoder: {result.encoder}",
                parent=self,
            )
        else:
            self.status_var.set("Export failed.")
            messagebox.showerror("Export Failed", result.error or "Unknown error", parent=self)

        if result.warnings:
            self.warning_text.configure(state="normal")
            self.warning_text.delete("1.0", tk.END)
            for warning in result.warnings:
                self.warning_text.insert(tk.END, f"- {warning}\n")
            self.warning_text.configure(state="disabled")

    def cancel_export(self) -> None:
        if self.export_thread and self.export_thread.is_alive():
            self.cancel_event.set()
            self.status_var.set("Canceling export...")
            self._append_log("Cancel requested.")

    def _set_busy(self, busy: bool) -> None:
        self.export_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.open_project_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.progress.start(10)
        else:
            self.progress.stop()

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"{line}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")


def launch_gui() -> None:
    app = WfpCompilerApp()
    app.mainloop()


if __name__ == "__main__":
    launch_gui()
