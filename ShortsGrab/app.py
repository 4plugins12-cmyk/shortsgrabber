"""
ShortsGrab: download YouTube / TikTok / Instagram / Reddit videos and
make them Shorts-ready (9:16, high quality H.264).
"""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

import tkinter as tk

import audio_ui
import core
import tag_ui
import theme
from tags import safe_name as tags_safe
import twitch_ui
import video_ui

APP_NAME = "ShortsGrab"
CONFIG_PATH = Path.home() / ".shortsgrab.json"

BG = theme.BLACK
SIDEBAR = theme.SIDEBAR
CARD = theme.CARD
MUTED = theme.MUTED


def load_settings():
    try:
        return {**core.DEFAULT_SETTINGS, **json.loads(CONFIG_PATH.read_text())}
    except Exception:
        return dict(core.DEFAULT_SETTINGS)


def save_settings(s):
    try:
        CONFIG_PATH.write_text(json.dumps(s, indent=2))
    except Exception:
        pass


def open_path(path):
    path = str(path)
    if os.name == "nt":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ----------------------------------------------------------------------------
# One page per platform
# ----------------------------------------------------------------------------
class PlatformPage(ctk.CTkFrame):
    def __init__(self, master, app, key):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.app, self.key = app, key
        p = core.PLATFORMS[key]
        self.color = p["color"]
        self.last_file = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

        ctk.CTkLabel(self, text=p["label"], font=ctk.CTkFont(size=28, weight="bold"),
                     text_color=p["color"]).grid(row=0, column=0, sticky="w", padx=28, pady=(26, 0))
        ctk.CTkLabel(self, text=p["hint"], text_color=MUTED, font=ctk.CTkFont(size=13)
                     ).grid(row=1, column=0, sticky="w", padx=28, pady=(2, 14))

        # --- link box
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        card.grid(row=2, column=0, sticky="ew", padx=24)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text="Paste link(s), one per line", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 0))
        self.urls = ctk.CTkTextbox(card, height=86, fg_color="#151619", border_width=1,
                                   border_color="#2c2e33", font=ctk.CTkFont(size=13))
        self.urls.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(4, 10))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        row.grid_columnconfigure(5, weight=1)
        ctk.CTkButton(row, text="Paste", width=70, fg_color="#2c2e33", hover_color="#3a3d44",
                      command=self.paste).grid(row=0, column=0)
        ctk.CTkButton(row, text="Clear", width=60, fg_color="#2c2e33", hover_color="#3a3d44",
                      command=lambda: self.urls.delete("1.0", "end")).grid(row=0, column=1, padx=(6, 18))
        ctk.CTkLabel(row, text="Trim  start", text_color=MUTED).grid(row=0, column=2)
        self.t_start = ctk.CTkEntry(row, width=70, placeholder_text="0:00")
        self.t_start.grid(row=0, column=3, padx=(6, 8))
        ctk.CTkLabel(row, text="end", text_color=MUTED).grid(row=0, column=4, sticky="w")
        self.t_end = ctk.CTkEntry(row, width=70, placeholder_text="end")
        self.t_end.grid(row=0, column=5, padx=(6, 0), sticky="w")
        self.fmt = ctk.CTkSegmentedButton(row, values=["Video", "MP3"], width=130,
                                          selected_color=p["color"], selected_hover_color=p["hover"],
                                          command=self.on_fmt)
        self.fmt.set(app.settings.get("formats", {}).get(key, "Video"))
        self.fmt.grid(row=0, column=6, sticky="e", padx=(0, 10))
        if p.get("audio_only"):
            self.fmt.set("MP3")
            self.fmt.grid_remove()
        row.grid_columnconfigure(5, weight=1)
        self.btn = ctk.CTkButton(row, text="Download", width=150, height=36,
                                 font=ctk.CTkFont(size=14, weight="bold"),
                                 fg_color=p["color"], hover_color=p["hover"], command=self.start)
        self.btn.grid(row=0, column=7, sticky="e")

        # --- mode summary line
        self.summary = ctk.CTkLabel(self, text="", text_color=MUTED, font=ctk.CTkFont(size=12))
        self.summary.grid(row=3, column=0, sticky="w", padx=28, pady=(10, 0))

        # --- progress
        prog = ctk.CTkFrame(self, fg_color="transparent")
        prog.grid(row=4, column=0, sticky="ew", padx=24, pady=(8, 8))
        prog.grid_columnconfigure(0, weight=1)
        self.bar = ctk.CTkProgressBar(prog, progress_color=p["color"], height=10)
        self.bar.set(0)
        self.bar.grid(row=0, column=0, sticky="ew")
        self.cancel_btn = ctk.CTkButton(prog, text="Cancel", width=70, fg_color="#2c2e33",
                                        hover_color="#3a3d44", command=self.app.cancel)
        self.cancel_btn.grid(row=0, column=1, padx=(10, 0))
        self.status = ctk.CTkLabel(prog, text="Ready", text_color=MUTED, anchor="w")
        self.status.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.open_btn = ctk.CTkButton(prog, text="Show file", width=70, fg_color="#2c2e33",
                                      hover_color="#3a3d44", state="disabled", command=self.show_file)
        self.open_btn.grid(row=1, column=1, padx=(10, 0), pady=(4, 0))

        # --- log
        self.log = ctk.CTkTextbox(self, fg_color=CARD, corner_radius=12,
                                  font=ctk.CTkFont(family="Consolas", size=12), wrap="word")
        self.log.grid(row=5, column=0, sticky="nsew", padx=24, pady=(4, 24))
        self.log.configure(state="disabled")

    def on_fmt(self, value):
        self.app.settings.setdefault("formats", {})[self.key] = value
        save_settings(self.app.settings)
        self.refresh_summary()

    def refresh_summary(self):
        s = self.app.settings
        if self.fmt.get() == "MP3":
            self.btn.configure(text="Download MP3")
            ask = "tag editor opens after download" if s["mp3_ask_tags"] else "auto-tagged"
            self.summary.configure(text=f"Output: MP3 {s['mp3_quality'].split(' (')[0]}  •  cover art + "
                                        f"tags for Apple Music  •  {ask}   (change in Settings)")
            return
        self.btn.configure(text="Download")
        mode = s["aspect_mode"]
        res = "" if mode.startswith("Original") else "  •  " + s["resolution"].split(" (")[0]
        self.summary.configure(text=f"Output: {mode}{res}  •  {s['quality']}   (change in Settings)")

    def paste(self):
        try:
            text = self.clipboard_get().strip()
        except Exception:
            return
        cur = self.urls.get("1.0", "end").strip()
        self.urls.insert("end", ("\n" if cur else "") + text)

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
            open_path(Path(self.last_file).parent)

    def start(self):
        lines = [l.strip() for l in self.urls.get("1.0", "end").splitlines() if l.strip()]
        if not lines:
            self.write("Paste a link first.")
            return
        try:
            start = core.parse_time(self.t_start.get())
            end = core.parse_time(self.t_end.get())
        except ValueError as e:
            self.write(str(e))
            return
        if start is not None and end is not None and end <= start:
            self.write("Trim end has to be after the start.")
            return
        if (start is not None or end is not None) and len(lines) > 1:
            self.write("ℹ Trim only applies when there's a single link. Downloading full videos.")
            start = end = None
        for url in lines:
            if not url.startswith("http"):
                url = "https://" + url
            other = core.detect_platform(url)
            if other and other != self.key:
                self.write(f"ℹ That looks like a {core.PLATFORMS[other]['label']} link, "
                           f"handling it anyway.")
            self.app.enqueue(self, url, start, end, self.fmt.get())
        self.urls.delete("1.0", "end")


# ----------------------------------------------------------------------------
# Settings page
# ----------------------------------------------------------------------------
class SettingsPage(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.app = app
        s = app.settings
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Settings", font=ctk.CTkFont(size=28, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 10))

        r = 1
        r = self.section(r, "Shorts output")
        self.aspect = self.option(r, "Aspect ratio", core.ASPECT_MODES, s["aspect_mode"],
                                  "Blur fill keeps the whole video and fills the gaps with a blurred copy. "
                                  "Crop zooms in to fill the screen (best when the subject is centered)."); r += 1
        self.res = self.option(r, "Resolution", list(core.RESOLUTIONS), s["resolution"],
                               "1080x1920 is what YouTube Shorts plays at. Higher only helps if the source is 4K."); r += 1
        self.quality = self.option(r, "Quality", list(core.QUALITY), s["quality"],
                                   "Lower CRF = higher quality and bigger files. 18 is visually lossless."); r += 1
        self.speed = self.option(r, "Encode speed", list(core.SPEED), s["speed"],
                                 "'Best' squeezes a bit more quality per MB but takes 2-3x longer."); r += 1
        self.fps60 = self.check(r, "Convert to 60 fps", s["fps60"],
                                "Usually leave this off. Only useful if you want smoother motion on 30fps clips."); r += 1
        self.keep = self.check(r, "Also keep the original download", s["keep_original"],
                               "Saves the untouched file next to the Shorts version."); r += 1

        r = self.section(r, "MP3 / Apple Music")
        self.mp3q = self.option(r, "MP3 quality", list(core.MP3_QUALITY), s["mp3_quality"],
                                "320 kbps is the highest MP3 quality. Files are 44.1 kHz with ID3v2.3 tags, "
                                "which is what Apple Music reads most reliably."); r += 1
        self.ask_tags = self.check(r, "Open the tag editor after each MP3 download", s["mp3_ask_tags"],
                                   "Off = tags are filled in automatically from the video (title, artist, year, "
                                   "thumbnail as cover). You can still edit later in the MP3 Tagger tab."); r += 1
        self.mp3_rename = self.check(r, "Rename MP3s to 'Artist - Title'", s["mp3_rename"],
                                     "Keeps your music folder tidy."); r += 1
        self.square = self.check(r, "Square-crop cover art", s["mp3_square_cover"],
                                 "Video thumbnails are 16:9; Apple Music shows square covers. On = center crop."); r += 1

        r = self.section(r, "Download")
        self.h264 = self.check(r, "Prefer H.264 source (most compatible)", s["prefer_h264"],
                               "Off = grab the absolute highest resolution (may be VP9/AV1). "
                               "On = only matters if you use 'Original' mode and your editor can't open the file."); r += 1
        self.browser = self.option(r, "Browser cookies", core.COOKIE_BROWSERS, s["cookies_browser"],
                                   "Needed for Instagram (and private or age-restricted videos). Pick the browser "
                                   "you're logged in on. Firefox is the most reliable; close Chrome/Edge first."); r += 1

        f = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        f.grid(row=r, column=0, sticky="ew", padx=16, pady=4); r += 1
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text="cookies.txt file", width=150, anchor="w").grid(row=0, column=0, padx=14, pady=12)
        self.cookie_file = ctk.CTkEntry(f, placeholder_text="optional, overrides browser cookies")
        self.cookie_file.insert(0, s["cookies_file"])
        self.cookie_file.grid(row=0, column=1, sticky="ew", pady=12)
        ctk.CTkButton(f, text="Browse", width=80, fg_color="#2c2e33", hover_color="#3a3d44",
                      command=self.pick_cookies).grid(row=0, column=2, padx=14)

        r = self.section(r, "Save location")
        f = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        f.grid(row=r, column=0, sticky="ew", padx=16, pady=4); r += 1
        f.grid_columnconfigure(0, weight=1)
        self.out = ctk.CTkEntry(f)
        self.out.insert(0, s["output_dir"])
        self.out.grid(row=0, column=0, sticky="ew", padx=14, pady=12)
        ctk.CTkButton(f, text="Browse", width=80, fg_color="#2c2e33", hover_color="#3a3d44",
                      command=self.pick_out).grid(row=0, column=1, padx=(0, 14))

        r = self.section(r, "Maintenance")
        f = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        f.grid(row=r, column=0, sticky="ew", padx=16, pady=4); r += 1
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(f, text="Update downloader", width=160, command=self.update_ytdlp
                      ).grid(row=0, column=0, padx=14, pady=12)
        self.maint = ctk.CTkLabel(f, text=self.versions(), text_color=MUTED, anchor="w", justify="left")
        self.maint.grid(row=0, column=1, sticky="w")

        ctk.CTkButton(self, text="Save settings", height=38, font=ctk.CTkFont(size=14, weight="bold"),
                      command=self.save).grid(row=r, column=0, sticky="e", padx=16, pady=(16, 24))
        self.saved = ctk.CTkLabel(self, text="", text_color="#5fd38d")
        self.saved.grid(row=r, column=0, sticky="w", padx=20)

    # widgets helpers
    def section(self, r, title):
        ctk.CTkLabel(self, text=title.upper(), text_color=MUTED, font=ctk.CTkFont(size=11, weight="bold")
                     ).grid(row=r, column=0, sticky="w", padx=20, pady=(16, 4))
        return r + 1

    def option(self, r, label, values, value, help_text):
        f = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        f.grid(row=r, column=0, sticky="ew", padx=16, pady=4)
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text=label, width=150, anchor="w").grid(row=0, column=0, padx=14, pady=(12, 0), sticky="w")
        var = ctk.StringVar(value=value if value in values else values[0])
        ctk.CTkOptionMenu(f, values=values, variable=var, width=260, command=lambda _: self.save()
                          ).grid(row=0, column=1, sticky="w", pady=(12, 0))
        ctk.CTkLabel(f, text=help_text, text_color=MUTED, font=ctk.CTkFont(size=12), wraplength=620,
                     justify="left", anchor="w").grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(4, 10))
        return var

    def check(self, r, label, value, help_text):
        f = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        f.grid(row=r, column=0, sticky="ew", padx=16, pady=4)
        var = ctk.BooleanVar(value=value)
        ctk.CTkSwitch(f, text=label, variable=var, command=self.save).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 0))
        ctk.CTkLabel(f, text=help_text, text_color=MUTED, font=ctk.CTkFont(size=12), wraplength=620,
                     justify="left", anchor="w").grid(row=1, column=0, sticky="w", padx=14, pady=(4, 10))
        return var

    def pick_out(self):
        d = filedialog.askdirectory(initialdir=self.out.get() or str(Path.home()))
        if d:
            self.out.delete(0, "end"); self.out.insert(0, d); self.save()

    def pick_cookies(self):
        f = filedialog.askopenfilename(filetypes=[("cookies.txt", "*.txt"), ("All files", "*.*")])
        if f:
            self.cookie_file.delete(0, "end"); self.cookie_file.insert(0, f); self.save()

    def versions(self):
        import yt_dlp
        ff = "found" if core.find_ffmpeg() else "MISSING"
        js = "found" if core.has_js_runtime() else "missing (YouTube quality may be limited)"
        return f"Downloader {yt_dlp.version.__version__}   •   ffmpeg {ff}   •   Deno {js}"

    def update_ytdlp(self):
        if getattr(sys, "frozen", False):
            self.maint.configure(text="This is the packaged .exe. Re-run the GitHub build to get the newest "
                                      "downloader (it always pulls the latest).")
            return
        self.maint.configure(text="Updating...")

        def work():
            r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"],
                               capture_output=True, text=True)
            msg = "Updated. Restart ShortsGrab to use it." if r.returncode == 0 else "Update failed:\n" + r.stderr[-300:]
            self.after(0, lambda: self.maint.configure(text=msg))
        threading.Thread(target=work, daemon=True).start()

    def save(self):
        s = self.app.settings
        s.update(
            aspect_mode=self.aspect.get(), resolution=self.res.get(), quality=self.quality.get(),
            speed=self.speed.get(), fps60=self.fps60.get(), keep_original=self.keep.get(),
            prefer_h264=self.h264.get(), cookies_browser=self.browser.get(),
            mp3_quality=self.mp3q.get(), mp3_ask_tags=self.ask_tags.get(),
            mp3_rename=self.mp3_rename.get(), mp3_square_cover=self.square.get(),
            cookies_file=self.cookie_file.get().strip(),
            output_dir=self.out.get().strip() or core.DEFAULT_SETTINGS["output_dir"],
        )
        save_settings(s)
        self.app.refresh_summaries()
        self.app.tagger.editor.square_cover = s["mp3_square_cover"]
        self.saved.configure(text="✓ Saved")
        self.after(1500, lambda: self.saved.configure(text=""))


# ----------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------
def accent_for(key):
    if key in core.PLATFORMS:
        return core.PLATFORMS[key]["color"]
    return {"twitch": theme.TWITCH, "gameplay": theme.LIGHT_BLUE, "convert": theme.LIGHT_BLUE,
            "splitter": theme.LIGHT_BLUE, "studio": theme.RED, "tagger": theme.RED,
            "settings": theme.SETTINGS}.get(key, theme.SETTINGS)


def text_on(color):
    r, g, b = theme.hex_to_rgb(color)
    return "#071018" if (0.299 * r + 0.587 * g + 0.114 * b) > 165 else "white"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        core.setup_path()
        ctk.set_appearance_mode("dark")
        self.title(APP_NAME)
        self.geometry("1260x800")
        self.minsize(1120, 720)
        self.configure(fg_color=theme.BLACK)
        self.settings = load_settings()
        self.settings.setdefault("gp_sources", [])

        self.jobs = queue.Queue()
        self.ui_events = queue.Queue()
        self.cancel_event = threading.Event()
        self.pending = 0
        self.tag_queue = []
        self.tag_dialog = None
        self.current = None
        self.accent = theme.SETTINGS
        self.last_file = None
        self._anim = 0

        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---- sidebar
        side = self.side = ctk.CTkFrame(self, fg_color=theme.SIDEBAR, corner_radius=0, width=220)
        self.side_color = theme.SIDEBAR
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(2, weight=1)
        self.edge = ctk.CTkFrame(self, fg_color=self.accent, corner_radius=0, width=3)
        self.edge.grid(row=0, column=1, sticky="ns")

        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(24, 14))
        self.logo = ctk.CTkLabel(brand, text=APP_NAME, font=ctk.CTkFont(size=23, weight="bold"))
        self.logo.pack(anchor="w")
        ctk.CTkLabel(brand, text="download • edit • post", text_color=theme.MUTED,
                     font=ctk.CTkFont(size=12)).pack(anchor="w")

        self.nav = ctk.CTkFrame(side, fg_color="transparent")
        self.nav.grid(row=1, column=0, sticky="new", padx=10)
        self.nav.grid_columnconfigure(0, weight=1)

        content = ctk.CTkFrame(self, fg_color=theme.BLACK, corner_radius=0)
        content.grid(row=0, column=2, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        # ---- pages
        self.pages = {}
        for key in core.PLATFORMS:
            self.pages[key] = PlatformPage(content, self, key)
        self.twitch = self.pages["twitch"] = twitch_ui.TwitchPage(content, self)
        self.pages["gameplay"] = video_ui.GameplayPage(content, self)
        self.pages["convert"] = video_ui.ConverterPage(content, self)
        self.pages["splitter"] = video_ui.SplitterPage(content, self)
        self.studio = self.pages["studio"] = audio_ui.AudioStudioPage(content, self)
        self.tagger = self.pages["tagger"] = tag_ui.TaggerPage(content, self)
        holder = ctk.CTkFrame(content, fg_color=theme.BLACK, corner_radius=0)
        self.settings_page = SettingsPage(holder, self)
        self.settings_page.pack(fill="both", expand=True)
        self.pages["settings"] = holder
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        # ---- dropdown sections
        sites = [(k, p["label"]) for k, p in core.PLATFORMS.items()] + [("twitch", "Twitch")]
        self.sections = [
            ("sites", "Sites", sites),
            ("video", "Video Editor", [("gameplay", "Gameplay Split"), ("convert", "Shorts Converter"),
                                       ("splitter", "Splitter")]),
            ("mp3", "MP3 Editor", [("studio", "Audio Studio"), ("tagger", "MP3 Tagger")]),
        ]
        self.section_of, self.headers, self.items, self.open_section = {}, {}, {}, None
        row = 0
        for sid, title, entries in self.sections:
            hdr = ctk.CTkButton(self.nav, text="", anchor="w", height=34, corner_radius=8,
                                fg_color="transparent", hover_color="#1f2024", text_color=theme.MUTED,
                                font=ctk.CTkFont(size=12, weight="bold"),
                                command=lambda s=sid: self.toggle_section(s))
            hdr.grid(row=row, column=0, sticky="ew", pady=(8 if row else 0, 0))
            hdr._title = title.upper()
            self.headers[sid] = hdr
            row += 1
            box = ctk.CTkFrame(self.nav, fg_color="transparent")
            box.grid(row=row, column=0, sticky="ew")
            box.grid_columnconfigure(0, weight=1)
            box._row = row
            row += 1
            for i, (key, label) in enumerate(entries):
                b = ctk.CTkButton(box, text="   " + label, anchor="w", height=38, corner_radius=9,
                                  font=ctk.CTkFont(size=14, weight="bold"), fg_color="transparent",
                                  hover_color="#222327", text_color=theme.TEXT,
                                  command=lambda k=key: self.show(k))
                b.grid(row=i, column=0, sticky="ew", padx=(6, 0), pady=1)
                self.items[key] = b
                self.section_of[key] = sid
            hdr._box = box

        bottom = ctk.CTkFrame(side, fg_color="transparent")
        bottom.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 16))
        bottom.grid_columnconfigure(0, weight=1)
        self.items["settings"] = ctk.CTkButton(
            bottom, text="   Settings", anchor="w", height=36, corner_radius=9, fg_color="transparent",
            hover_color="#222327", text_color=theme.TEXT, command=lambda: self.show("settings"))
        self.items["settings"].grid(row=0, column=0, sticky="ew", pady=1)
        ctk.CTkButton(bottom, text="   Open output folder", anchor="w", height=36, corner_radius=9,
                      fg_color="transparent", hover_color="#222327", text_color=theme.TEXT,
                      command=self.open_output).grid(row=1, column=0, sticky="ew", pady=1)

        self.refresh_summaries()
        self.toggle_section("sites", force=True)
        self.show("youtube", animate=False)
        self.bind_all("<space>", self.on_space, add="+")

        threading.Thread(target=self.worker, daemon=True).start()
        self.after(80, self.pump)

    # ---- navigation -----------------------------------------------------
    def toggle_section(self, sid, force=False):
        """Accordion: opening one section closes the others."""
        opening = force or self.open_section != sid
        self.open_section = sid if opening else None
        for s, hdr in self.headers.items():
            is_open = s == self.open_section
            hdr.configure(text=("▾  " if is_open else "▸  ") + hdr._title)
            if is_open:
                hdr._box.grid(row=hdr._box._row, column=0, sticky="ew")
            else:
                hdr._box.grid_remove()
        self.color_headers(self.accent)

    def color_headers(self, accent):
        cur = self.section_of.get(self.current)
        for s, hdr in self.headers.items():
            hdr.configure(text_color=accent if s == cur else theme.MUTED)

    def show(self, key, animate=True):
        prev, prev_accent = self.current, self.accent
        side_from = self.side_color
        self.current = key
        target = accent_for(key)
        sec = self.section_of.get(key)
        if sec and self.open_section != sec:
            self.toggle_section(sec, force=True)
        page = self.pages[key]
        page.tkraise()
        if key == "settings":
            self.settings_page.configure(fg_color=theme.tint(prev_accent))
        for k, b in self.items.items():
            if k not in (key, prev):
                b.configure(fg_color="transparent", text_color=theme.TEXT, hover_color="#222327")
        self._anim += 1
        anim = self._anim
        steps = 14 if animate else 1

        def step(i):
            if anim != self._anim:
                return
            t = theme.ease(i / steps)
            c = theme.mix(prev_accent, target, t)
            bg = theme.tint(c)
            page.configure(fg_color=bg)
            # Video Editor + MP3 Editor: sidebar matches the page background
            side_to = theme.tint(target) if sec in ("video", "mp3") else theme.SIDEBAR
            self.side_color = theme.mix(side_from, side_to, t)
            self.side.configure(fg_color=self.side_color)
            if key == "settings":
                self.settings_page.configure(fg_color=bg)
            sel = self.items[key]
            sel.configure(fg_color=theme.mix(self.side_color, target, t), hover_color=target,
                          text_color=text_on(target) if t > 0.5 else theme.TEXT)
            if prev and prev != key:
                self.items[prev].configure(fg_color=theme.mix(prev_accent, self.side_color, t),
                                           text_color=theme.TEXT, hover_color="#222327")
            self.edge.configure(fg_color=c)
            self.logo.configure(text_color=theme.mix(theme.TEXT, c, 0.85))
            self.color_headers(c)
            self.accent = c
            if i < steps:
                self.after(16, lambda: step(i + 1))
            elif prev and prev != key:
                self.items[prev].configure(fg_color="transparent")
        step(1 if not animate else 0)

    def on_space(self, event):
        if self.current != "studio":
            return
        w = self.focus_get()
        if isinstance(w, (tk.Entry, tk.Text)):
            return
        self.studio.toggle()
        return "break"

    def refresh_summaries(self):
        for k in list(core.PLATFORMS) + ["twitch"]:
            if k in self.pages:
                self.pages[k].refresh_summary()

    def save(self):
        save_settings(self.settings)

    def open_output(self):
        d = Path(self.settings["output_dir"])
        d.mkdir(parents=True, exist_ok=True)
        open_path(d)

    # ---- jobs -----------------------------------------------------------
    def enqueue(self, page, url, start, end, fmt="Video", extra=None):
        settings = {**self.settings, **(extra or {})}
        key = getattr(page, "key", "youtube")

        if key == "soundcloud" and "/sets/" in url:
            page.write(f"➕ Queued playlist: {url}")
            self.enqueue_task(page, url, lambda emit, cancel: self.run_set(url, settings, emit, cancel), quiet=True)
            return

        def task(emit, cancel):
            return core.Job(url, key, settings, emit, start, end, cancel_flag=cancel, fmt=fmt).run()
        page.write(f"➕ Queued{' (MP3)' if fmt == 'MP3' else ''}: {url}")
        self.enqueue_task(page, url, task, quiet=True)

    def run_set(self, url, settings, emit, cancel):
        """SoundCloud set: download every track as an album (shared album tag, numbered tracks)."""
        import yt_dlp
        emit("status", "Reading playlist...")
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
                               **core.cookie_opts(settings)}) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = [e for e in (info.get("entries") or []) if e and (e.get("url") or e.get("webpage_url"))]
        if not entries:
            raise RuntimeError("That playlist has no tracks I can download.")
        album = info.get("title") or "Playlist"
        folder = Path(settings["output_dir"]) / tags_safe(album)
        emit("log", f"Playlist: {album}  ({len(entries)} tracks) → {folder}")
        last, failed = None, 0
        for i, e in enumerate(entries, 1):
            if cancel():
                raise core.Cancelled()
            s = {**settings, "output_dir": str(folder), "album_override": album,
                 "album_artist": info.get("uploader") or "", "track_no": i, "track_total": len(entries),
                 "mp3_ask_tags": False}
            n = len(entries)
            sub = lambda k, p, i=i: emit(k, ((i - 1) + p) / n if k == "progress" else p) if k != "done" else None
            try:
                emit("status", f"Track {i}/{n}")
                last = core.Job(e.get("url") or e["webpage_url"], "soundcloud", s, sub,
                                cancel_flag=cancel, fmt="MP3").run()
                emit("log", f"  ✓ {i:02d}. {Path(last).name}")
            except core.Cancelled:
                raise
            except Exception as ex:
                failed += 1
                emit("log", f"  ✖ {i:02d}. {core.friendly_error(ex, 'soundcloud').splitlines()[0]}")
        if failed:
            emit("log", f"ℹ {failed} track{'s' if failed != 1 else ''} couldn't be downloaded.")
        if not last:
            raise RuntimeError("None of the tracks could be downloaded.")
        return last

    def enqueue_task(self, page, label, func, quiet=False):
        """Queue any background job: func(emit, cancel_flag) -> output path (or None)."""
        self.pending += 1
        if not quiet:
            page.write(f"➕ Queued: {label}")
        self.jobs.put((page, label, func))

    def cookie_opts(self):
        return core.cookie_opts(self.settings)

    def cancel(self):
        self.cancel_event.set()

    def worker(self):
        while True:
            page, label, func = self.jobs.get()
            self.cancel_event.clear()
            sent = {"done": False}

            def emit(kind, payload, pg=page):
                if kind == "done":
                    sent["done"] = True
                self.ui_events.put((pg, kind, payload))
            emit("begin", label)
            try:
                result = func(emit, self.cancel_event.is_set)
                if result and not sent["done"]:
                    emit("progress", 1.0)
                    emit("done", str(result))
            except core.Cancelled:
                emit("fail", "Cancelled.")
            except Exception as e:
                emit("fail", core.friendly_error(e, getattr(page, "key", "")))
            finally:
                emit("end", None)

    def pump(self):
        try:
            while True:
                page, kind, payload = self.ui_events.get_nowait()
                if kind == "begin":
                    page.bar.set(0)
                    page.write(f"\n▶ {payload}")
                    page.status.configure(text="Starting...")
                elif kind == "log":
                    page.write(payload)
                elif kind == "status":
                    page.status.configure(text=payload)
                elif kind == "progress":
                    page.bar.set(payload)
                elif kind == "done":
                    page.last_file = self.last_file = payload
                    page.open_btn.configure(state="normal")
                    page.status.configure(text="✓ Done: " + Path(payload).name)
                    page.write("✓ Saved: " + payload)
                elif kind == "fail":
                    page.bar.set(0)
                    page.status.configure(text="✖ Failed" if payload != "Cancelled." else "Cancelled")
                    page.write("✖ " + payload)
                elif kind == "tag":
                    self.tag_queue.append((page, payload))
                    self.next_tag_dialog()
                elif kind == "end":
                    self.pending -= 1
                    if self.pending > 0:
                        page.write(f"   ({self.pending} more in queue)")
                    else:
                        self.bell_done()
        except queue.Empty:
            pass
        self.after(80, self.pump)

    def bell_done(self):
        try:
            if os.name == "nt":
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    # ---- tag pop-ups, one at a time
    def next_tag_dialog(self):
        if self.tag_dialog is not None or not self.tag_queue:
            return
        page, job = self.tag_queue.pop(0)

        def closed(final_path):
            self.tag_dialog = None
            if final_path:
                page.last_file = self.last_file = final_path
                page.write("🏷 Tagged: " + Path(final_path).name)
            self.after(100, self.next_tag_dialog)

        self.tag_dialog = tag_ui.TagDialog(self, job["path"], job["tags"],
                                           self.settings["mp3_square_cover"],
                                           self.settings["mp3_rename"], closed)


if __name__ == "__main__":
    App().mainloop()
