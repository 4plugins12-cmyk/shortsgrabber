"""Audio Studio tab: live-preview audio editor (trim, EQ, bass, speed, reverb, meter, export)."""
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

import audio_engine as ae
import core
import tags as tagmod
from theme import BLACK, CARD, CARD_DARK, MUTED, TEXT, GREY, GREY_HOVER, RED, RED_HOVER

AUDIO_TYPES = [("Audio / video", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.wma *.mp4 *.mov *.mkv *.webm"),
               ("All files", "*.*")]


def fmt_time(s):
    s = max(0.0, s)
    return f"{int(s // 60)}:{s % 60:04.1f}"


class Knob:
    """Labelled horizontal slider with a value readout. Double-click the name to reset."""

    def __init__(self, parent, row, label, lo, hi, default, fmt, on_change, steps=None):
        self.default, self.fmt, self.on_change = default, fmt, on_change
        name = ctk.CTkLabel(parent, text=label, anchor="w", width=92, font=ctk.CTkFont(size=12))
        name.grid(row=row, column=0, sticky="w", padx=(14, 4), pady=4)
        name.bind("<Double-Button-1>", lambda e: self.set(self.default, fire=True))
        self.slider = ctk.CTkSlider(parent, from_=lo, to=hi, number_of_steps=steps, command=self._moved,
                                    button_color=RED, button_hover_color=RED_HOVER, progress_color=RED,
                                    height=16)
        self.slider.grid(row=row, column=1, sticky="ew", pady=4)
        self.value = ctk.CTkLabel(parent, text="", width=64, anchor="e", text_color=MUTED,
                                  font=ctk.CTkFont(size=12))
        self.value.grid(row=row, column=2, sticky="e", padx=(4, 14))
        self.set(default)

    def _moved(self, v):
        self.value.configure(text=self.fmt(v))
        self.on_change(v)

    def set(self, v, fire=False):
        self.slider.set(v)
        self.value.configure(text=self.fmt(v))
        if fire:
            self.on_change(v)


class AudioStudioPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=BLACK, corner_radius=0)
        self.app = app
        self.eng = ae.AudioEngine()
        self.eng.status_cb = lambda m: self.after(0, lambda: self.set_status(m))
        self.drag = None
        self.peak_disp = [0.0, 0.0]
        self.peak_hold = [0.0, 0.0]
        self.hold_t = [0, 0]
        self.clip_t = 0
        self.last_export = None
        self.preset_name = "Flat"

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(self, text="Audio Studio", font=ctk.CTkFont(size=28, weight="bold"), text_color=RED
                     ).grid(row=0, column=0, sticky="w", padx=28, pady=(22, 0))

        # ---- file bar
        bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        bar.grid(row=1, column=0, sticky="ew", padx=24, pady=(10, 0))
        bar.grid_columnconfigure(2, weight=1)
        ctk.CTkButton(bar, text="Open audio…", width=120, height=34, fg_color=RED, hover_color=RED_HOVER,
                      font=ctk.CTkFont(size=13, weight="bold"), command=self.open_file
                      ).grid(row=0, column=0, padx=(12, 6), pady=10)
        ctk.CTkButton(bar, text="Last download", width=110, height=34, fg_color=GREY, hover_color=GREY_HOVER,
                      command=self.open_last).grid(row=0, column=1, padx=(0, 10))
        self.file_lbl = ctk.CTkLabel(bar, text="No file loaded (MP3, WAV, M4A, FLAC, or even a video)",
                                     anchor="w", text_color=MUTED)
        self.file_lbl.grid(row=0, column=2, sticky="w")
        ctk.CTkLabel(bar, text="Preset", text_color=MUTED).grid(row=0, column=3, padx=(6, 6))
        self.preset = ctk.CTkOptionMenu(bar, values=list(ae.PRESETS), width=150, fg_color=RED,
                                        button_color=RED_HOVER, button_hover_color="#9e1626",
                                        command=self.apply_preset)
        self.preset.grid(row=0, column=4, padx=(0, 10))
        self.bypass = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(bar, text="Bypass (A/B)", variable=self.bypass, progress_color=RED,
                      command=lambda: self.eng.set("bypass", self.bypass.get())).grid(row=0, column=5, padx=(0, 14))

        # ---- waveform + meter
        wave = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        wave.grid(row=2, column=0, sticky="ew", padx=24, pady=(10, 0))
        wave.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(wave, height=130, bg="#08080a", highlightthickness=0, cursor="hand2")
        self.canvas.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=12)
        self.meter = tk.Canvas(wave, width=96, height=130, bg="#08080a", highlightthickness=0)
        self.meter.grid(row=0, column=1, padx=(0, 12), pady=12)
        self.canvas.bind("<Configure>", lambda e: self.draw_wave())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))
        self.draw_meter_frame()

        # ---- transport
        tr = ctk.CTkFrame(self, fg_color="transparent")
        tr.grid(row=3, column=0, sticky="ew", padx=24, pady=(8, 0))
        self.play_btn = ctk.CTkButton(tr, text="▶  Play", width=96, height=34, fg_color=RED,
                                      hover_color=RED_HOVER, font=ctk.CTkFont(size=13, weight="bold"),
                                      command=self.toggle)
        self.play_btn.pack(side="left")
        ctk.CTkButton(tr, text="■", width=40, height=34, fg_color=GREY, hover_color=GREY_HOVER,
                      command=self.stop).pack(side="left", padx=6)
        self.loop = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(tr, text="Loop", variable=self.loop, progress_color=RED, width=60,
                      command=lambda: setattr(self.eng, "loop", self.loop.get())).pack(side="left", padx=(6, 12))
        self.eng.loop = True
        self.time_lbl = ctk.CTkLabel(tr, text="0:00.0 / 0:00.0", font=ctk.CTkFont(family="Consolas", size=13))
        self.time_lbl.pack(side="left", padx=(0, 18))
        for label, which in (("Start", 0), ("End", 1)):
            ctk.CTkLabel(tr, text=label, text_color=MUTED).pack(side="left", padx=(6, 4))
            e = ctk.CTkEntry(tr, width=70)
            e.pack(side="left")
            e.bind("<Return>", lambda ev, w=which: self.trim_from_entry(w))
            e.bind("<FocusOut>", lambda ev, w=which: self.trim_from_entry(w))
            setattr(self, f"trim_e{which}", e)
            ctk.CTkButton(tr, text="⇤ here" if which == 0 else "here ⇥", width=60, height=28, fg_color=GREY,
                          hover_color=GREY_HOVER, command=lambda w=which: self.trim_here(w)
                          ).pack(side="left", padx=(4, 8))
        ctk.CTkButton(tr, text="Reset trim", width=86, height=28, fg_color=GREY, hover_color=GREY_HOVER,
                      command=self.reset_trim).pack(side="left")
        self.status = ctk.CTkLabel(tr, text="", text_color=MUTED)
        self.status.pack(side="right")

        # ---- controls
        ctl = ctk.CTkFrame(self, fg_color="transparent")
        ctl.grid(row=4, column=0, sticky="nsew", padx=24, pady=(10, 0))
        ctl.grid_columnconfigure((0, 2), weight=3, uniform="c")
        ctl.grid_columnconfigure(1, weight=4, uniform="c")
        ctl.grid_rowconfigure(0, weight=1)

        c1 = self.card(ctl, 0, "Level & Tone")
        self.k_vol = Knob(c1, 1, "Volume", -24, 24, 0, lambda v: f"{v:+.1f} dB",
                          lambda v: self.eng.set("volume_db", v), steps=96)
        self.k_bass = Knob(c1, 2, "Bass boost", 0, 24, 0, lambda v: f"+{v:.1f} dB",
                           lambda v: self.eng.set("bass_db", v), steps=48)
        ctk.CTkLabel(c1, text="Bass freq", anchor="w", font=ctk.CTkFont(size=12)
                     ).grid(row=3, column=0, sticky="w", padx=(14, 4), pady=4)
        self.bass_f = ctk.CTkSegmentedButton(c1, values=list(ae.BASS_FREQS), selected_color=RED,
                                             selected_hover_color=RED_HOVER, font=ctk.CTkFont(size=11),
                                             command=lambda v: self.eng.set("bass_freq", ae.BASS_FREQS[v]))
        self.bass_f.set("80 Hz")
        self.bass_f.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(0, 14), pady=4)
        self.k_treb = Knob(c1, 4, "Treble", -12, 12, 0, lambda v: f"{v:+.1f} dB",
                           lambda v: self.eng.set("treble_db", v), steps=48)
        self.k_width = Knob(c1, 5, "Stereo width", 0, 2, 1, lambda v: f"{v * 100:.0f}%",
                            lambda v: self.eng.set("width", v), steps=40)
        ctk.CTkLabel(c1, text="Low cut", anchor="w", font=ctk.CTkFont(size=12)
                     ).grid(row=6, column=0, sticky="w", padx=(14, 4), pady=4)
        self.lowcut = ctk.CTkOptionMenu(c1, values=list(ae.LOWCUT), width=110, fg_color=GREY,
                                        button_color=GREY_HOVER,
                                        command=lambda v: self.eng.set("lowcut", ae.LOWCUT[v]))
        self.lowcut.grid(row=6, column=1, sticky="w", pady=4)
        self.limiter = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(c1, text="Limiter (stops clipping)", variable=self.limiter, progress_color=RED,
                      font=ctk.CTkFont(size=12), command=lambda: self.eng.set("limiter", self.limiter.get())
                      ).grid(row=7, column=0, columnspan=3, sticky="w", padx=14, pady=(6, 10))

        c2 = self.card(ctl, 1, "10-band EQ")
        eqf = ctk.CTkFrame(c2, fg_color="transparent")
        eqf.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=8)
        c2.grid_rowconfigure(1, weight=1)
        self.eq_sliders, self.eq_vals = [], []
        for i, lab in enumerate(ae.EQ_LABELS):
            eqf.grid_columnconfigure(i, weight=1)
            v = ctk.CTkLabel(eqf, text="0", text_color=MUTED, font=ctk.CTkFont(size=11), width=30)
            v.grid(row=0, column=i)
            s = ctk.CTkSlider(eqf, from_=-12, to=12, number_of_steps=48, orientation="vertical", height=150,
                              width=16, button_color=RED, button_hover_color=RED_HOVER, progress_color=GREY,
                              command=lambda val, i=i: self.eq_moved(i, val))
            s.set(0)
            s.grid(row=1, column=i, pady=2)
            ctk.CTkLabel(eqf, text=lab, font=ctk.CTkFont(size=11)).grid(row=2, column=i)
            self.eq_sliders.append(s)
            self.eq_vals.append(v)
        ctk.CTkButton(c2, text="Flatten EQ", width=100, height=26, fg_color=GREY, hover_color=GREY_HOVER,
                      command=self.flatten_eq).grid(row=2, column=0, columnspan=3, pady=(4, 10))

        c3 = self.card(ctl, 2, "Effects")
        self.k_speed = Knob(c3, 1, "Speed", 0.5, 1.5, 1.0, self.speed_text,
                            lambda v: self.eng.set("speed", round(v, 3)), steps=100)
        self.k_rmix = Knob(c3, 2, "Reverb", 0, 1, 0, lambda v: f"{v * 100:.0f}%",
                           lambda v: self.eng.set("reverb_mix", v), steps=50)
        self.k_rsize = Knob(c3, 3, "Room size", 0.4, 5, 2.0, lambda v: f"{v:.1f} s", self.size_moved, steps=46)
        self.k_fin = Knob(c3, 4, "Fade in", 0, 10, 0, lambda v: f"{v:.1f} s",
                          lambda v: self.eng.set("fade_in", v), steps=40)
        self.k_fout = Knob(c3, 5, "Fade out", 0, 10, 0, lambda v: f"{v:.1f} s",
                           lambda v: self.eng.set("fade_out", v), steps=40)
        ctk.CTkLabel(c3, text="Speed changes pitch too (classic slowed / sped-up sound).\n"
                              "Double-click any control name to reset it.",
                     text_color=MUTED, font=ctk.CTkFont(size=11), justify="left", wraplength=270, anchor="w"
                     ).grid(row=6, column=0, columnspan=3, sticky="ew", padx=14, pady=(4, 10))
        self._size_after = None

        # ---- export bar
        ex = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        ex.grid(row=5, column=0, sticky="ew", padx=24, pady=(10, 22))
        ex.grid_columnconfigure(4, weight=1)
        self.ex_fmt = ctk.CTkOptionMenu(ex, values=["MP3 320 kbps", "WAV 16-bit", "WAV 24-bit"], width=130,
                                        fg_color=GREY, button_color=GREY_HOVER)
        self.ex_fmt.grid(row=0, column=0, padx=(12, 8), pady=10)
        self.norm = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(ex, text="Normalize (-14 LUFS)", variable=self.norm, progress_color=RED,
                      font=ctk.CTkFont(size=12)).grid(row=0, column=1, padx=6)
        self.keep_tags = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(ex, text="Keep tags + cover", variable=self.keep_tags, progress_color=RED,
                      font=ctk.CTkFont(size=12)).grid(row=0, column=2, padx=6)
        self.ex_bar = ctk.CTkProgressBar(ex, progress_color=RED, height=8, width=160)
        self.ex_bar.set(0)
        self.ex_bar.grid(row=0, column=3, padx=10)
        self.ex_msg = ctk.CTkLabel(ex, text="", text_color=MUTED, anchor="w")
        self.ex_msg.grid(row=0, column=4, sticky="w")
        self.tag_btn = ctk.CTkButton(ex, text="Open in Tagger", width=110, fg_color=GREY, hover_color=GREY_HOVER,
                                     state="disabled", command=self.to_tagger)
        self.tag_btn.grid(row=0, column=5, padx=4)
        self.ex_btn = ctk.CTkButton(ex, text="Export", width=110, height=34, fg_color=RED, hover_color=RED_HOVER,
                                    font=ctk.CTkFont(size=14, weight="bold"), command=self.export)
        self.ex_btn.grid(row=0, column=6, padx=(4, 12))

        self.after(40, self.tick)

    # ---- helpers ---------------------------------------------------------
    def card(self, parent, col, title):
        c = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12)
        c.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 5, 0 if col == 2 else 5))
        c.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(c, text=title, font=ctk.CTkFont(size=13, weight="bold")
                     ).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(10, 4))
        return c

    def set_status(self, msg):
        self.status.configure(text=msg)

    @staticmethod
    def speed_text(v):
        tag = "slowed" if v < 0.98 else "sped up" if v > 1.02 else "normal"
        return f"{v:.2f}x {tag}"

    def size_moved(self, v):
        # re-rendering reverb is heavier, so wait until the slider settles
        if self._size_after:
            self.after_cancel(self._size_after)
        self._size_after = self.after(250, lambda: self.eng.set("reverb_size", round(v, 1)))

    def eq_moved(self, i, v):
        self.eq_vals[i].configure(text=f"{v:+.0f}" if abs(v) >= 0.5 else "0")
        self.eng.set_eq(i, v)

    def flatten_eq(self):
        for i, s in enumerate(self.eq_sliders):
            s.set(0)
            self.eq_moved(i, 0)

    def apply_preset(self, name):
        self.preset_name = name
        self.eng.apply_preset(name)
        self.sync_controls()

    def sync_controls(self):
        p = self.eng.params
        self.k_vol.set(p["volume_db"]); self.k_bass.set(p["bass_db"]); self.k_treb.set(p["treble_db"])
        self.k_width.set(p["width"]); self.k_speed.set(p["speed"]); self.k_rmix.set(p["reverb_mix"])
        self.k_rsize.set(p["reverb_size"]); self.k_fin.set(p["fade_in"]); self.k_fout.set(p["fade_out"])
        self.bass_f.set(next((k for k, v in ae.BASS_FREQS.items() if v == p["bass_freq"]), "80 Hz"))
        self.lowcut.set(next((k for k, v in ae.LOWCUT.items() if v == p["lowcut"]), "Off"))
        for i, g in enumerate(p["eq"]):
            self.eq_sliders[i].set(g)
            self.eq_vals[i].configure(text=f"{g:+.0f}" if abs(g) >= 0.5 else "0")

    # ---- file ------------------------------------------------------------
    def open_file(self):
        f = filedialog.askopenfilename(title="Open audio", filetypes=AUDIO_TYPES,
                                       initialdir=self.app.settings.get("output_dir"))
        if f:
            self.load(f)

    def open_last(self):
        last = getattr(self.app, "last_file", None)
        if last and Path(last).exists():
            self.load(last)
        else:
            self.set_status("Download something first (MP3 or video).")

    def load(self, path):
        self.set_status("Loading…")
        self.file_lbl.configure(text=Path(path).name, text_color=TEXT)

        def work():
            try:
                self.eng.load(path)
                self.after(0, self.loaded)
            except Exception as e:
                self.after(0, lambda: (self.set_status(""), self.file_lbl.configure(
                    text=f"✖ {e}", text_color="#ff6b6b")))
        threading.Thread(target=work, daemon=True).start()

    def loaded(self):
        self.set_status("")
        self.file_lbl.configure(text=f"{Path(self.eng.path).name}    {fmt_time(self.eng.duration)}",
                                text_color=TEXT)
        self.update_trim_entries()
        self.draw_wave()
        self.tag_btn.configure(state="disabled")
        self.ex_msg.configure(text="")
        self.ex_bar.set(0)

    # ---- transport -------------------------------------------------------
    def toggle(self):
        if self.eng.playing:
            self.eng.pause()
        else:
            err = self.eng.play()
            if err:
                self.set_status(err)

    def stop(self):
        self.eng.stop()

    def to_samples(self, sec):
        return int(round(sec * self.eng.sr))

    def update_trim_entries(self):
        s, e = self.eng.trim
        for w, v in ((0, s), (1, e)):
            ent = getattr(self, f"trim_e{w}")
            ent.delete(0, "end")
            ent.insert(0, fmt_time(v / self.eng.sr))

    def trim_from_entry(self, which):
        if self.eng.data is None:
            return
        try:
            v = core.parse_time(getattr(self, f"trim_e{which}").get().strip())
        except ValueError:
            v = None
        if v is not None:
            self.set_trim(which, self.to_samples(v))
        self.update_trim_entries()

    def trim_here(self, which):
        if self.eng.data is not None:
            self.set_trim(which, int(self.eng.state.pos))

    def set_trim(self, which, samples):
        n = len(self.eng.data)
        s, e = self.eng.trim
        min_len = self.eng.sr // 2
        if which == 0:
            s = max(0, min(samples, e - min_len))
        else:
            e = min(n, max(samples, s + min_len))
        self.eng.trim = (s, e)
        if not (s <= self.eng.state.pos < e):
            self.eng.state.pos = s
        self.update_trim_entries()
        self.draw_wave()

    def reset_trim(self):
        if self.eng.data is not None:
            self.eng.trim = (0, len(self.eng.data))
            self.update_trim_entries()
            self.draw_wave()

    # ---- waveform --------------------------------------------------------
    def x_of(self, samples):
        w = max(self.canvas.winfo_width(), 10)
        return samples / max(len(self.eng.data), 1) * w

    def draw_wave(self):
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 10), max(c.winfo_height(), 10)
        if self.eng.data is None or self.eng.env is None:
            c.create_text(w / 2, h / 2, text="Open a song to see its waveform", fill="#55575e",
                          font=("Segoe UI", 12))
            return
        env = self.eng.env
        s, e = self.eng.trim
        xs, xe = self.x_of(s), self.x_of(e)
        mid = h / 2
        c.create_rectangle(xs, 0, xe, h, fill="#1a0b0e", width=0)
        for x in range(0, w, 2):
            i0 = int(x / w * len(env))
            i1 = max(i0 + 1, int((x + 2) / w * len(env)))
            a = float(env[i0:i1].max()) * (h / 2 - 6)
            col = RED if xs <= x <= xe else "#3a3b40"
            c.create_line(x, mid - a, x, mid + a + 1, fill=col, width=2)
        for x in (xs, xe):
            c.create_line(x, 0, x, h, fill="white", width=2)
            c.create_polygon(x - 6, 0, x + 6, 0, x, 9, fill="white")
        dur = self.eng.duration
        step = next(t for t in (5, 10, 15, 30, 60, 120, 300, 600) if dur / t < 14)
        t = step
        while t < dur:
            x = t / dur * w
            c.create_text(x, h - 7, text=f"{int(t // 60)}:{int(t % 60):02d}", fill="#55575e",
                          font=("Segoe UI", 8))
            t += step
        self.playhead = c.create_line(0, 0, 0, h, fill="#ffffff", width=1, dash=(3, 2))

    def on_press(self, ev):
        if self.eng.data is None:
            return
        s, e = self.eng.trim
        xs, xe = self.x_of(s), self.x_of(e)
        if abs(ev.x - xs) < 9:
            self.drag = 0
        elif abs(ev.x - xe) < 9:
            self.drag = 1
        else:
            self.drag = None
            w = max(self.canvas.winfo_width(), 10)
            self.eng.seek(ev.x / w * self.eng.duration)

    def on_drag(self, ev):
        if self.drag is None or self.eng.data is None:
            return
        w = max(self.canvas.winfo_width(), 10)
        self.set_trim(self.drag, int(min(max(ev.x, 0), w) / w * len(self.eng.data)))

    # ---- meter -----------------------------------------------------------
    METER_MIN = -48.0

    def m_y(self, db, h):
        db = max(self.METER_MIN, min(3.0, db))
        return 12 + (3.0 - db) / (3.0 - self.METER_MIN) * (h - 40)

    def draw_meter_frame(self):
        m = self.meter
        m.delete("all")
        h = 130
        for db in (0, -6, -12, -24, -36, -48):
            y = self.m_y(db, h)
            m.create_text(80, y, text=str(db), fill="#55575e", font=("Segoe UI", 7))
            m.create_line(8, y, 66, y, fill="#1d1e22")
        self.m_bars = [m.create_rectangle(0, 0, 0, 0, width=0) for _ in range(2)]
        self.m_holds = [m.create_line(0, 0, 0, 0, fill="white", width=2) for _ in range(2)]
        self.m_clip = m.create_rectangle(8, 2, 66, 7, fill="#2a1013", width=0)
        self.m_text = m.create_text(37, h - 6, text="-inf", fill=MUTED, font=("Consolas", 8))
        m.create_text(21, h - 20, text="L", fill="#55575e", font=("Segoe UI", 7))
        m.create_text(53, h - 20, text="R", fill="#55575e", font=("Segoe UI", 7))

    def update_meter(self, now_ms):
        h = 130
        pk = self.eng.meter[:2]
        for i in range(2):
            self.peak_disp[i] = max(pk[i], self.peak_disp[i] * 0.86)     # smooth fall
            if pk[i] >= self.peak_hold[i] or now_ms - self.hold_t[i] > 1200:
                self.peak_hold[i] = pk[i]
                self.hold_t[i] = now_ms
            db = ae.lin2db(self.peak_disp[i])
            x0 = 8 + i * 32
            y = self.m_y(db, h)
            col = RED if db > -1 else "#ffb020" if db > -9 else "#3ddc84"
            self.meter.coords(self.m_bars[i], x0, y, x0 + 26, self.m_y(self.METER_MIN, h))
            self.meter.itemconfigure(self.m_bars[i], fill=col)
            hy = self.m_y(ae.lin2db(self.peak_hold[i]), h)
            if self.peak_hold[i] > 0.004:
                self.meter.coords(self.m_holds[i], x0, hy, x0 + 26, hy)
            else:
                self.meter.coords(self.m_holds[i], 0, 0, 0, 0)
        if max(pk) >= 0.999:
            self.clip_t = now_ms
        self.meter.itemconfigure(self.m_clip, fill=RED if now_ms - self.clip_t < 1500 else "#2a1013")
        top = max(self.peak_hold)
        self.meter.itemconfigure(self.m_text, text=f"{ae.lin2db(top):+.1f} dB" if top > 1e-4 else "-inf")

    # ---- loop ------------------------------------------------------------
    def tick(self):
        visible = self.app.current == "studio"
        if visible or self.eng.playing:
            now = int(self.tk.call("clock", "milliseconds"))
            if self.eng.data is not None:
                pos = self.eng.position
                self.time_lbl.configure(text=f"{fmt_time(pos)} / {fmt_time(self.eng.duration)}")
                if hasattr(self, "playhead"):
                    x = self.x_of(self.eng.state.pos)
                    self.canvas.coords(self.playhead, x, 0, x, self.canvas.winfo_height())
            self.play_btn.configure(text="⏸  Pause" if self.eng.playing else "▶  Play")
            self.update_meter(now)
        self.after(33, self.tick)

    # ---- export ----------------------------------------------------------
    def export(self):
        if self.eng.data is None:
            self.ex_msg.configure(text="Open a file first.")
            return
        fmt = self.ex_fmt.get()
        ext = ".mp3" if fmt.startswith("MP3") else ".wav"
        src = Path(self.eng.path)
        label = self.preset_name if self.preset_name != "Flat" else "edit"
        folder = Path(self.app.settings["output_dir"]) / "Audio Studio"
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / f"{tagmod.safe_name(src.stem)} ({label}){ext}"
        i = 2
        while dst.exists():
            dst = folder / f"{tagmod.safe_name(src.stem)} ({label}) {i}{ext}"
            i += 1
        self.ex_btn.configure(state="disabled")
        self.ex_msg.configure(text="Exporting…", text_color=MUTED)
        keep = self.keep_tags.get() and ext == ".mp3"
        norm = self.norm.get()

        def prog(f):
            self.after(0, lambda: self.ex_bar.set(f))

        def work():
            try:
                self.eng.export(dst, fmt, norm, prog)
                if keep:
                    t = tagmod.read_tags(str(src)) if src.suffix.lower() == ".mp3" else tagmod.empty_tags()
                    if not t.get("title") or t["title"] == src.stem:
                        t["title"] = src.stem
                    if self.preset_name != "Flat":
                        t["title"] = f"{t['title']} ({self.preset_name})"
                    tagmod.write_tags(str(dst), t)
                self.after(0, lambda: self.exported(str(dst)))
            except Exception as e:
                self.after(0, lambda: (self.ex_msg.configure(text=f"✖ {e}", text_color="#ff6b6b"),
                                       self.ex_btn.configure(state="normal")))
        threading.Thread(target=work, daemon=True).start()

    def exported(self, path):
        self.last_export = path
        self.ex_btn.configure(state="normal")
        self.ex_bar.set(1)
        self.ex_msg.configure(text=f"✓ Saved {Path(path).name}", text_color="#5fd38d")
        self.tag_btn.configure(state="normal" if path.endswith(".mp3") else "disabled")

    def to_tagger(self):
        if self.last_export:
            self.app.tagger.add_paths([self.last_export])
            self.app.tagger.select(self.last_export)
            self.app.show("tagger")
