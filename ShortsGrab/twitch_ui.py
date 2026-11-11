"""Twitch Clips tab: grab a channel's most-viewed clips and turn them into Shorts."""
import re
import threading
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
import yt_dlp

from theme import BLACK as BG, CARD, MUTED, GREY, GREY_HOVER, TWITCH as PURPLE, TWITCH_HOVER as PURPLE_HOVER
import core
import video_tools as vt

STYLES = ["Shorts (Settings style)", "Gameplay split", "Original clips"]

RANGES = {"Last 24 hours": "24hr", "Last 7 days": "7d", "Last 30 days": "30d", "All time": "all"}
COUNTS = ["5", "10", "15", "20"]


def parse_channel(text):
    text = (text or "").strip().rstrip("/")
    m = re.search(r"twitch\.tv/([A-Za-z0-9_]{2,25})", text)
    if m:
        return m.group(1).lower()
    if re.fullmatch(r"@?[A-Za-z0-9_]{2,25}", text):
        return text.lstrip("@").lower()
    return None


class _Quiet:
    def debug(self, m): pass
    def info(self, m): pass
    def warning(self, m): pass
    def error(self, m): pass


def fetch_top_clips(channel, range_key, count, cookies=None):
    """Return the `count` most-viewed clips for the channel in the given range."""
    url = f"https://www.twitch.tv/{channel}/clips?filter=clips&range={range_key}"
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
            "playlistend": max(20, count), "skip_download": True, "logger": _Quiet()}
    if cookies:
        opts.update(cookies)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    clips = [e for e in (info.get("entries") or []) if e and e.get("url")]
    clips.sort(key=lambda e: e.get("view_count") or 0, reverse=True)
    return clips[:count]


def fmt_views(n):
    n = n or 0
    return f"{n / 1_000_000:.1f}M" if n >= 1_000_000 else f"{n / 1000:.1f}K" if n >= 1000 else str(n)


class TwitchPage(ctk.CTkFrame):
    key = "twitch"

    def __init__(self, master, app):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.app = app
        self.clips = []
        self.checks = []
        self.rows = []
        self.last_file = None
        self.channel = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=3)
        self.grid_rowconfigure(5, weight=2)

        ctk.CTkLabel(self, text="Twitch", font=ctk.CTkFont(size=28, weight="bold"), text_color=PURPLE
                     ).grid(row=0, column=0, sticky="w", padx=28, pady=(26, 0))
        ctk.CTkLabel(self, text="Enter a channel to grab its most-viewed clips and convert them into Shorts.",
                     text_color=MUTED).grid(row=1, column=0, sticky="w", padx=28, pady=(2, 12))

        # ---- search bar
        bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        bar.grid(row=2, column=0, sticky="ew", padx=24)
        bar.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(bar, height=36, placeholder_text="twitch.tv/channelname  or just  channelname",
                                  font=ctk.CTkFont(size=13))
        self.entry.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=12)
        self.entry.bind("<Return>", lambda e: self.find())
        self.range = ctk.CTkOptionMenu(bar, values=list(RANGES), width=140, fg_color=PURPLE,
                                       button_color=PURPLE_HOVER, button_hover_color="#5a22b8")
        self.range.set("Last 24 hours")
        self.range.grid(row=0, column=1, padx=4)
        ctk.CTkLabel(bar, text="Top", text_color=MUTED).grid(row=0, column=2, padx=(8, 4))
        self.count = ctk.CTkOptionMenu(bar, values=COUNTS, width=64, fg_color=PURPLE,
                                       button_color=PURPLE_HOVER, button_hover_color="#5a22b8")
        self.count.set("10")
        self.count.grid(row=0, column=3, padx=(0, 8))
        self.find_btn = ctk.CTkButton(bar, text="Find clips", width=120, height=36, fg_color=PURPLE,
                                      hover_color=PURPLE_HOVER, font=ctk.CTkFont(size=14, weight="bold"),
                                      command=self.find)
        self.find_btn.grid(row=0, column=4, padx=(4, 12))

        # ---- results list
        res = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        res.grid(row=3, column=0, sticky="nsew", padx=24, pady=(10, 0))
        res.grid_columnconfigure(0, weight=1)
        res.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(res, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        head.grid_columnconfigure(1, weight=1)
        self.all_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(head, text="", width=24, variable=self.all_var, command=self.toggle_all,
                        fg_color=PURPLE, hover_color=PURPLE_HOVER
                        ).grid(row=0, column=0)
        self.res_title = ctk.CTkLabel(head, text="No channel loaded", anchor="w",
                                      font=ctk.CTkFont(size=13, weight="bold"))
        self.res_title.grid(row=0, column=1, sticky="w")
        self.style = ctk.CTkOptionMenu(head, values=STYLES, width=190, fg_color=GREY, button_color=GREY_HOVER,
                                       command=self.style_changed)
        self.style.set(app.settings.get("twitch_style", STYLES[0]))
        self.style.grid(row=0, column=2, padx=(0, 8))
        self.go_btn = ctk.CTkButton(head, text="Download & convert selected", width=220, height=34,
                                    fg_color=PURPLE, hover_color=PURPLE_HOVER, state="disabled",
                                    font=ctk.CTkFont(size=13, weight="bold"), command=self.convert)
        self.go_btn.grid(row=0, column=3)
        self.list = ctk.CTkScrollableFrame(res, fg_color="transparent")
        self.list.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 8))
        self.list.grid_columnconfigure(1, weight=1)

        # ---- progress (same attribute names the main app's job runner uses)
        prog = ctk.CTkFrame(self, fg_color="transparent")
        prog.grid(row=4, column=0, sticky="ew", padx=24, pady=(10, 6))
        prog.grid_columnconfigure(0, weight=1)
        self.summary = ctk.CTkLabel(prog, text="", text_color=MUTED, font=ctk.CTkFont(size=12))
        self.summary.grid(row=0, column=0, columnspan=2, sticky="w")
        self.bar = ctk.CTkProgressBar(prog, progress_color=PURPLE, height=10)
        self.bar.set(0)
        self.bar.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        ctk.CTkButton(prog, text="Cancel", width=70, fg_color=GREY, hover_color=GREY_HOVER,
                      command=app.cancel).grid(row=1, column=1, padx=(10, 0), pady=(4, 0))
        self.status = ctk.CTkLabel(prog, text="Ready", text_color=MUTED, anchor="w")
        self.status.grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.open_btn = ctk.CTkButton(prog, text="Show file", width=70, fg_color=GREY, hover_color=GREY_HOVER,
                                      state="disabled", command=self.show_folder)
        self.open_btn.grid(row=2, column=1, padx=(10, 0), pady=(4, 0))

        self.log = ctk.CTkTextbox(self, fg_color=CARD, corner_radius=12, height=110,
                                  font=ctk.CTkFont(family="Consolas", size=12), wrap="word")
        self.log.grid(row=5, column=0, sticky="nsew", padx=24, pady=(4, 24))
        self.log.configure(state="disabled")
        self.refresh_summary()

    # ---- shared helpers used by the app's job runner
    def write(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def style_changed(self, v):
        self.app.settings["twitch_style"] = v
        self.app.save()
        self.refresh_summary()

    def refresh_summary(self):
        s = self.app.settings
        if hasattr(self, "style") and self.style.get() == "Gameplay split":
            n = len(s.get("gp_sources", []))
            self.summary.configure(text=f"Output: gameplay split (layout + {n} gameplay file{'s' if n != 1 else ''} "
                                        "from Video Editor → Gameplay Split)")
            return
        if hasattr(self, "style") and self.style.get() == "Original clips":
            self.summary.configure(text="Output: original clips, untouched")
            return
        res = "" if s["aspect_mode"].startswith("Original") else "  •  " + s["resolution"].split(" (")[0]
        self.summary.configure(text=f"Output: {s['aspect_mode']}{res}  •  {s['quality']}   (change in Settings)")

    def show_folder(self):
        from app import open_path
        if self.last_file:
            open_path(Path(self.last_file).parent)

    # ---- finding clips
    def find(self):
        ch = parse_channel(self.entry.get())
        if not ch:
            self.write("Enter a Twitch channel link or name, e.g. twitch.tv/shroud")
            return
        rng_label = self.range.get()
        n = int(self.count.get())
        self.find_btn.configure(state="disabled", text="Searching…")
        self.res_title.configure(text=f"Looking up {ch}…")
        cookies = self.app.cookie_opts()

        def work():
            try:
                clips = fetch_top_clips(ch, RANGES[rng_label], n, cookies)
                self.after(0, lambda: self.show_clips(ch, rng_label, clips))
            except Exception as e:
                msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")
                self.after(0, lambda: self.find_failed(ch, msg))
        threading.Thread(target=work, daemon=True).start()

    def find_failed(self, ch, msg):
        self.find_btn.configure(state="normal", text="Find clips")
        self.res_title.configure(text="No clips loaded")
        self.write(f"✖ Couldn't load clips for {ch}: {msg}\n→ Check the channel name. If it's right, "
                   "Twitch may have changed something. Update the downloader in Settings.")

    def show_clips(self, ch, rng_label, clips):
        self.find_btn.configure(state="normal", text="Find clips")
        for r in self.rows:
            r.destroy()
        self.rows, self.checks, self.clips = [], [], clips
        self.channel = ch
        if not clips:
            self.res_title.configure(text=f"{ch}: no clips in {rng_label.lower()}")
            self.go_btn.configure(state="disabled")
            self.write(f"No clips found for {ch} in {rng_label.lower()}. Try a longer time range.")
            return
        self.res_title.configure(text=f"{ch}: top {len(clips)} clips, {rng_label.lower()}")
        for i, c in enumerate(clips):
            var = ctk.BooleanVar(value=True)
            row = ctk.CTkFrame(self.list, fg_color="#18191c", corner_radius=8)
            row.pack(fill="x", pady=2, padx=4)
            row.grid_columnconfigure(2, weight=1)
            ctk.CTkCheckBox(row, text="", width=24, variable=var, fg_color=PURPLE, hover_color=PURPLE_HOVER).grid(row=0, column=0, padx=(10, 2), pady=6)
            ctk.CTkLabel(row, text=f"#{i + 1}", width=34, text_color=PURPLE,
                         font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=1)
            ctk.CTkLabel(row, text=(c.get("title") or c.get("id") or "clip")[:80], anchor="w",
                         font=ctk.CTkFont(size=13)).grid(row=0, column=2, sticky="w", padx=6)
            when = ""
            if c.get("timestamp"):
                when = datetime.fromtimestamp(c["timestamp"]).strftime("%b %d %H:%M")
            dur = int(c.get("duration") or 0)
            meta = f"{fmt_views(c.get('view_count'))} views   •   {dur}s   •   {when}"
            ctk.CTkLabel(row, text=meta, text_color=MUTED, font=ctk.CTkFont(size=12)
                         ).grid(row=0, column=3, padx=(6, 12))
            self.rows.append(row)
            self.checks.append(var)
        self.all_var.set(True)
        self.go_btn.configure(state="normal")

    def toggle_all(self):
        for v in self.checks:
            v.set(self.all_var.get())

    # ---- converting
    def convert(self):
        picked = [(i, c) for i, (c, v) in enumerate(zip(self.clips, self.checks)) if v.get()]
        if not picked:
            self.write("Tick at least one clip.")
            return
        folder = Path(self.app.settings["output_dir"]) / "Twitch" / \
            f"{self.channel} {datetime.now().strftime('%Y-%m-%d')}"
        style = self.style.get()
        if style == "Gameplay split" and not self.app.settings.get("gp_sources"):
            self.write("✖ No gameplay video set. Add one in Video Editor → Gameplay Split first.")
            return
        for i, c in picked:
            extra = {"output_dir": str(folder), "name_prefix": f"{i + 1:02d} "}
            if style == "Shorts (Settings style)":
                self.app.enqueue(self, c["url"], None, None, "Video", extra)
                continue
            extra["aspect_mode"] = "Original (no change)"
            if style == "Original clips":
                self.app.enqueue(self, c["url"], None, None, "Video", extra)
                continue
            settings = {**self.app.settings, **extra}

            def task(emit, cancel, url=c["url"], settings=settings):
                # download the untouched clip, then build the split; only the split is reported as done
                inner = lambda k, p: emit(k, p * 0.4 if k == "progress" else p) if k != "done" else None
                orig = core.Job(url, "twitch", settings, inner, cancel_flag=cancel).run()
                gp = vt.pick_gameplay(settings["gp_sources"])
                dst = vt.unique_path(folder / f"{Path(orig).stem} (split).mp4")
                out = vt.gameplay_split(orig, gp, dst, settings, emit, cancel, p_range=(0.4, 1.0))
                if not settings.get("keep_original"):
                    Path(orig).unlink(missing_ok=True)
                return out
            self.app.enqueue_task(self, c.get("title") or c["url"], task)
        self.write(f"Saving to: {folder}")
