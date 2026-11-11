"""Video Editor tabs: Gameplay Split, Shorts Converter, Splitter (black + light blue)."""
import os
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

import core
import video_tools as vt
from theme import BLACK, CARD, CARD_DARK, MUTED, TEXT, GREY, GREY_HOVER, LIGHT_BLUE, LIGHT_BLUE_HOVER

VIDEO_TYPES = [("Videos", "*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.flv *.wmv"), ("All files", "*.*")]
BLUE_TEXT = "#06131c"   # dark text on light-blue buttons


def blue_button(parent, text, cmd, width=150, height=36, size=14):
    return ctk.CTkButton(parent, text=text, width=width, height=height, fg_color=LIGHT_BLUE,
                         hover_color=LIGHT_BLUE_HOVER, text_color=BLUE_TEXT,
                         font=ctk.CTkFont(size=size, weight="bold"), command=cmd)


def grey_button(parent, text, cmd, width=80, height=28):
    return ctk.CTkButton(parent, text=text, width=width, height=height, fg_color=GREY,
                         hover_color=GREY_HOVER, command=cmd)


class FileList(ctk.CTkFrame):
    """Card with a title, add/clear buttons and a scrolling list of files."""

    def __init__(self, master, title, hint, on_change=None, height=150):
        super().__init__(master, fg_color=CARD, corner_radius=12)
        self.files, self.rows, self.on_change = [], [], on_change
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        head.grid_columnconfigure(0, weight=1)
        self.title_lbl = ctk.CTkLabel(head, text=title, anchor="w", font=ctk.CTkFont(size=13, weight="bold"))
        self.title_lbl.grid(row=0, column=0, sticky="w")
        self.title = title
        grey_button(head, "+ Files", self.add_files, 62).grid(row=0, column=1, padx=2)
        grey_button(head, "+ Folder", self.add_folder, 68).grid(row=0, column=2, padx=2)
        grey_button(head, "✕", self.clear, 30).grid(row=0, column=3, padx=(2, 0))
        self.box = ctk.CTkScrollableFrame(self, fg_color=CARD_DARK, height=height, corner_radius=8)
        self.box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.empty = ctk.CTkLabel(self.box, text=hint, text_color=MUTED, font=ctk.CTkFont(size=12))
        self.empty.pack(pady=18)

    def add(self, paths):
        for p in paths:
            p = str(Path(p))
            if p not in self.files and Path(p).is_file():
                self.files.append(p)
        self.redraw()

    def add_files(self):
        self.add(filedialog.askopenfilenames(title="Choose videos", filetypes=VIDEO_TYPES))

    def add_folder(self):
        d = filedialog.askdirectory()
        if d:
            self.add(vt.list_videos(d))

    def clear(self):
        self.files = []
        self.redraw()

    def remove(self, p):
        self.files.remove(p)
        self.redraw()

    def redraw(self):
        for r in self.rows:
            r.destroy()
        self.rows = []
        if self.files:
            self.empty.pack_forget()
        else:
            self.empty.pack(pady=18)
        for p in self.files:
            r = ctk.CTkFrame(self.box, fg_color="transparent")
            r.pack(fill="x")
            ctk.CTkLabel(r, text=Path(p).name, anchor="w", font=ctk.CTkFont(size=12)).pack(side="left", padx=6)
            ctk.CTkButton(r, text="✕", width=24, height=22, fg_color="transparent", hover_color=GREY,
                          text_color=MUTED, command=lambda p=p: self.remove(p)).pack(side="right")
            self.rows.append(r)
        n = len(self.files)
        self.title_lbl.configure(text=f"{self.title}  ({n})" if n else self.title)
        if self.on_change:
            self.on_change()


class ToolPage(ctk.CTkFrame):
    """Base page: heading + body + progress/log footer that the app's job runner drives."""

    def __init__(self, master, app, key, title, subtitle):
        super().__init__(master, fg_color=BLACK, corner_radius=0)
        self.app, self.key = app, key
        self.last_file = None
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=28, weight="bold"), text_color=LIGHT_BLUE
                     ).grid(row=0, column=0, sticky="w", padx=28, pady=(24, 0))
        ctk.CTkLabel(self, text=subtitle, text_color=MUTED).grid(row=1, column=0, sticky="w", padx=28, pady=(2, 10))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=2, column=0, sticky="nsew", padx=24)
        self.grid_rowconfigure(2, weight=1)

        prog = ctk.CTkFrame(self, fg_color="transparent")
        prog.grid(row=3, column=0, sticky="ew", padx=24, pady=(10, 4))
        prog.grid_columnconfigure(0, weight=1)
        self.bar = ctk.CTkProgressBar(prog, progress_color=LIGHT_BLUE, height=10)
        self.bar.set(0)
        self.bar.grid(row=0, column=0, sticky="ew")
        grey_button(prog, "Cancel", app.cancel, 70).grid(row=0, column=1, padx=(10, 0))
        self.status = ctk.CTkLabel(prog, text="Ready", text_color=MUTED, anchor="w")
        self.status.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.open_btn = grey_button(prog, "Show file", self.show_file, 70)
        self.open_btn.configure(state="disabled")
        self.open_btn.grid(row=1, column=1, padx=(10, 0), pady=(2, 0))
        self.log = ctk.CTkTextbox(self, fg_color=CARD, corner_radius=12, height=90,
                                  font=ctk.CTkFont(family="Consolas", size=12), wrap="word")
        self.log.grid(row=4, column=0, sticky="ew", padx=24, pady=(4, 22))
        self.log.configure(state="disabled")

    def write(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def show_file(self):
        if not self.last_file or not os.path.exists(self.last_file):
            return
        if os.name == "nt":
            subprocess.Popen(f'explorer /select,"{os.path.normpath(self.last_file)}"')
        else:
            from app import open_path
            open_path(Path(self.last_file).parent)

    def refresh_summary(self):
        pass

    def out_dir(self, name):
        d = Path(self.app.settings["output_dir"]) / name
        d.mkdir(parents=True, exist_ok=True)
        return d


# ----------------------------------------------------------------------------
class GameplayPage(ToolPage):
    def __init__(self, master, app):
        super().__init__(master, app, "gameplay", "Gameplay Split",
                         "Your clip on top, gameplay underneath, made in bulk. Great for Twitch and podcast clips.")
        s = {**vt.GP_DEFAULTS, **app.settings}
        b = self.body
        b.grid_columnconfigure((0, 1), weight=1, uniform="g")
        b.grid_columnconfigure(2, weight=0)
        b.grid_rowconfigure(0, weight=1)
        self.clips = FileList(b, "Main clips", "Add the videos that go in the main section", self.changed)
        self.clips.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.gp = FileList(b, "Gameplay", "Add gameplay footage (Minecraft parkour,\nSubway Surfers, GTA…)",
                           self.gp_changed)
        self.gp.grid(row=0, column=1, sticky="nsew", padx=5)
        self.gp.add([p for p in s["gp_sources"] if Path(p).is_file()])

        opt = ctk.CTkFrame(b, fg_color=CARD, corner_radius=12, width=300)
        opt.grid(row=0, column=2, rowspan=2, sticky="nsew", padx=(5, 0))
        opt.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(opt, text="Layout", font=ctk.CTkFont(size=13, weight="bold")
                     ).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(10, 2))
        self.preview = tk.Canvas(opt, width=90, height=160, bg="#08080a", highlightthickness=0)
        self.preview.grid(row=1, column=0, rowspan=4, padx=(14, 10), pady=4, sticky="n")

        def lab(r, t):
            ctk.CTkLabel(opt, text=t, text_color=MUTED, font=ctk.CTkFont(size=12), anchor="w"
                         ).grid(row=r, column=1, sticky="w", padx=(0, 14))
        lab(1, "Gameplay goes")
        self.pos = ctk.CTkSegmentedButton(opt, values=["Bottom", "Top"], selected_color=LIGHT_BLUE,
                                          selected_hover_color=LIGHT_BLUE_HOVER, text_color="white",
                                          command=lambda v: self.save_opts())
        self.pos.set(s["gp_position"])
        self.pos.grid(row=2, column=1, sticky="ew", padx=(0, 14))
        self.ratio_lbl = ctk.CTkLabel(opt, text="", text_color=MUTED, font=ctk.CTkFont(size=12), anchor="w")
        self.ratio_lbl.grid(row=3, column=1, sticky="w", padx=(0, 14), pady=(6, 0))
        self.ratio = ctk.CTkSlider(opt, from_=0.35, to=0.65, number_of_steps=30, button_color=LIGHT_BLUE,
                                   progress_color=LIGHT_BLUE, button_hover_color=LIGHT_BLUE_HOVER,
                                   command=lambda v: self.save_opts())
        self.ratio.set(s["gp_ratio"])
        self.ratio.grid(row=4, column=1, sticky="ew", padx=(0, 14))

        r = 5
        ctk.CTkLabel(opt, text="Main clip fit", text_color=MUTED, font=ctk.CTkFont(size=12)
                     ).grid(row=r, column=0, columnspan=2, sticky="w", padx=14, pady=(10, 0))
        self.fit = ctk.CTkSegmentedButton(opt, values=["Fill (crop)", "Fit (blur)"], selected_color=LIGHT_BLUE,
                                          selected_hover_color=LIGHT_BLUE_HOVER,
                                          command=lambda v: self.save_opts())
        self.fit.set(s["gp_top_fit"])
        self.fit.grid(row=r + 1, column=0, columnspan=2, sticky="ew", padx=14)
        self.vol_lbl = ctk.CTkLabel(opt, text="", text_color=MUTED, font=ctk.CTkFont(size=12))
        self.vol_lbl.grid(row=r + 2, column=0, columnspan=2, sticky="w", padx=14, pady=(10, 0))
        self.vol = ctk.CTkSlider(opt, from_=0, to=1, number_of_steps=20, button_color=LIGHT_BLUE,
                                 progress_color=LIGHT_BLUE, button_hover_color=LIGHT_BLUE_HOVER,
                                 command=lambda v: self.save_opts())
        self.vol.set(s["gp_volume"])
        self.vol.grid(row=r + 3, column=0, columnspan=2, sticky="ew", padx=14)
        ctk.CTkLabel(opt, text="Divider line", text_color=MUTED, font=ctk.CTkFont(size=12)
                     ).grid(row=r + 4, column=0, columnspan=2, sticky="w", padx=14, pady=(10, 0))
        self.div = ctk.CTkSegmentedButton(opt, values=["None", "Thin", "Thick"], selected_color=LIGHT_BLUE,
                                          selected_hover_color=LIGHT_BLUE_HOVER,
                                          command=lambda v: self.save_opts())
        self.div.set({0: "None", 6: "Thin", 14: "Thick"}.get(s["gp_divider"], "None"))
        self.div.grid(row=r + 5, column=0, columnspan=2, sticky="ew", padx=14)
        self.rand = ctk.BooleanVar(value=s["gp_random_start"])
        ctk.CTkSwitch(opt, text="Random gameplay start point", variable=self.rand, progress_color=LIGHT_BLUE,
                      font=ctk.CTkFont(size=12), command=self.save_opts
                      ).grid(row=r + 6, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 4))
        ctk.CTkLabel(opt, text="Several gameplay files? Each clip gets a\nrandom one. Short gameplay loops.",
                     text_color=MUTED, font=ctk.CTkFont(size=11), justify="left"
                     ).grid(row=r + 7, column=0, columnspan=2, sticky="w", padx=14)
        self.go = blue_button(opt, "Make videos", self.start, width=200)
        self.go.grid(row=r + 8, column=0, columnspan=2, sticky="ew", padx=14, pady=(14, 14))
        self.save_opts(write=False)

    def gp_changed(self):
        self.app.settings["gp_sources"] = list(self.gp.files)
        self.app.save()

    def changed(self):
        n = len(self.clips.files)
        self.go.configure(text=f"Make {n} video{'s' if n != 1 else ''}" if n else "Make videos")

    def opts(self):
        return {"gp_position": self.pos.get(), "gp_ratio": round(self.ratio.get(), 3),
                "gp_top_fit": self.fit.get(), "gp_volume": round(self.vol.get(), 2),
                "gp_random_start": self.rand.get(),
                "gp_divider": {"None": 0, "Thin": 6, "Thick": 14}[self.div.get()]}

    def save_opts(self, write=True):
        o = self.opts()
        self.ratio_lbl.configure(text=f"Main clip size  {o['gp_ratio'] * 100:.0f}%")
        self.vol_lbl.configure(text=f"Gameplay audio  {o['gp_volume'] * 100:.0f}%"
                               + ("  (muted)" if o["gp_volume"] == 0 else ""))
        self.draw_preview(o)
        if write:
            self.app.settings.update(o)
            self.app.save()

    def draw_preview(self, o):
        c = self.preview
        c.delete("all")
        W, H = 90, 160
        div = {0: 0, 6: 2, 14: 5}[o["gp_divider"]]
        hm = (H - div) * o["gp_ratio"]
        top_is_main = o["gp_position"] == "Bottom"
        main_box = (0, 0, W, hm) if top_is_main else (0, H - hm, W, H)
        gp_box = (0, hm + div, W, H) if top_is_main else (0, 0, W, H - hm - div)
        c.create_rectangle(*main_box, fill="#1e3a4a", width=0)
        c.create_text((main_box[0] + main_box[2]) / 2, (main_box[1] + main_box[3]) / 2, text="CLIP",
                      fill=LIGHT_BLUE, font=("Segoe UI", 9, "bold"))
        c.create_rectangle(*gp_box, fill="#163322", width=0)
        c.create_text((gp_box[0] + gp_box[2]) / 2, (gp_box[1] + gp_box[3]) / 2, text="GAMEPLAY",
                      fill="#5fd38d", font=("Segoe UI", 8, "bold"))

    def start(self):
        if not self.clips.files:
            self.write("Add at least one main clip.")
            return
        if not self.gp.files:
            self.write("Add a gameplay video.")
            return
        settings = {**self.app.settings, **self.opts()}
        out = self.out_dir("Gameplay Split")
        for src in list(self.clips.files):
            def task(emit, cancel, src=src, settings=settings):
                gp = vt.pick_gameplay(self.gp.files)
                emit("log", f"Gameplay: {Path(gp).name}")
                dst = vt.unique_path(out / f"{Path(src).stem} (split).mp4")
                return vt.gameplay_split(src, gp, dst, settings, emit, cancel)
            self.app.enqueue_task(self, Path(src).name, task)


# ----------------------------------------------------------------------------
class ConverterPage(ToolPage):
    def __init__(self, master, app):
        super().__init__(master, app, "convert", "Shorts Converter",
                         "Turn videos already on your PC into 9:16 Shorts, in bulk.")
        b = self.body
        b.grid_columnconfigure(0, weight=1)
        b.grid_rowconfigure(0, weight=1)
        self.files = FileList(b, "Videos", "Add videos from your computer", self.changed, height=220)
        self.files.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        opt = ctk.CTkFrame(b, fg_color=CARD, corner_radius=12)
        opt.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ctk.CTkLabel(opt, text="Style", font=ctk.CTkFont(size=13, weight="bold")
                     ).pack(anchor="w", padx=14, pady=(10, 4))
        self.mode = ctk.CTkOptionMenu(opt, values=core.ASPECT_MODES[:3], width=220, fg_color=GREY,
                                      button_color=GREY_HOVER)
        cur = app.settings["aspect_mode"]
        self.mode.set(cur if cur in core.ASPECT_MODES[:3] else core.ASPECT_MODES[0])
        self.mode.pack(anchor="w", padx=14)
        ctk.CTkLabel(opt, text="Resolution / quality come from Settings.", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(anchor="w", padx=14, pady=(6, 0))
        ctk.CTkLabel(opt, text="Trim (optional, single file)", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).pack(anchor="w", padx=14, pady=(14, 2))
        row = ctk.CTkFrame(opt, fg_color="transparent")
        row.pack(anchor="w", padx=14)
        self.t0 = ctk.CTkEntry(row, width=70, placeholder_text="start")
        self.t0.pack(side="left")
        self.t1 = ctk.CTkEntry(row, width=70, placeholder_text="end")
        self.t1.pack(side="left", padx=6)
        self.go = blue_button(opt, "Convert", self.start, width=220)
        self.go.pack(anchor="w", padx=14, pady=(18, 14))

    def changed(self):
        n = len(self.files.files)
        self.go.configure(text=f"Convert {n} file{'s' if n != 1 else ''}" if n else "Convert")

    def start(self):
        if not self.files.files:
            self.write("Add some videos first.")
            return
        try:
            a, z = core.parse_time(self.t0.get()), core.parse_time(self.t1.get())
        except ValueError as e:
            self.write(str(e))
            return
        if (a is not None or z is not None) and len(self.files.files) > 1:
            self.write("ℹ Trim only applies to a single file, converting full videos.")
            a = z = None
        s = {**self.app.settings, "aspect_mode": self.mode.get()}
        out = self.out_dir("Converted")
        for src in list(self.files.files):
            self.app.enqueue_task(self, Path(src).name,
                                  lambda emit, cancel, src=src: vt.convert_file(src, out, s, emit, cancel, a, z))


# ----------------------------------------------------------------------------
class SplitterPage(ToolPage):
    LENGTHS = {"30s": 30, "59s": 59, "90s": 90, "2 min": 120, "3 min": 180}

    def __init__(self, master, app):
        super().__init__(master, app, "splitter", "Splitter",
                         "Chop long videos (streams, podcasts, gameplay) into Shorts-length parts.")
        b = self.body
        b.grid_columnconfigure(0, weight=1)
        b.grid_rowconfigure(0, weight=1)
        self.files = FileList(b, "Long videos", "Add videos to split", self.changed, height=220)
        self.files.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        opt = ctk.CTkFrame(b, fg_color=CARD, corner_radius=12)
        opt.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ctk.CTkLabel(opt, text="Part length", font=ctk.CTkFont(size=13, weight="bold")
                     ).pack(anchor="w", padx=14, pady=(10, 4))
        self.len = ctk.CTkSegmentedButton(opt, values=list(self.LENGTHS), selected_color=LIGHT_BLUE,
                                          selected_hover_color=LIGHT_BLUE_HOVER)
        self.len.set("59s")
        self.len.pack(anchor="w", padx=14)
        row = ctk.CTkFrame(opt, fg_color="transparent")
        row.pack(anchor="w", padx=14, pady=(8, 0))
        ctk.CTkLabel(row, text="or custom (sec)", text_color=MUTED, font=ctk.CTkFont(size=12)).pack(side="left")
        self.custom = ctk.CTkEntry(row, width=60)
        self.custom.pack(side="left", padx=6)
        self.shorts = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(opt, text="Convert parts to 9:16 (Settings style)", variable=self.shorts,
                      progress_color=LIGHT_BLUE, font=ctk.CTkFont(size=12)).pack(anchor="w", padx=14, pady=(14, 0))
        ctk.CTkLabel(opt, text="A last bit shorter than 5s is merged\ninto the part before it.",
                     text_color=MUTED, font=ctk.CTkFont(size=11), justify="left").pack(anchor="w", padx=14, pady=(8, 0))
        self.go = blue_button(opt, "Split", self.start, width=240)
        self.go.pack(anchor="w", padx=14, pady=(18, 14))

    def changed(self):
        n = len(self.files.files)
        self.go.configure(text=f"Split {n} video{'s' if n != 1 else ''}" if n else "Split")

    def start(self):
        if not self.files.files:
            self.write("Add a video first.")
            return
        seg = self.LENGTHS[self.len.get()]
        if self.custom.get().strip():
            try:
                seg = float(self.custom.get())
                assert seg >= 5
            except Exception:
                self.write("Custom length must be a number of seconds (5 or more).")
                return
        s, out, to_shorts = dict(self.app.settings), self.out_dir("Split"), self.shorts.get()
        for src in list(self.files.files):
            self.app.enqueue_task(self, Path(src).name, lambda emit, cancel, src=src:
                                  vt.split_file(src, out, seg, to_shorts, s, emit, cancel)[-1])
