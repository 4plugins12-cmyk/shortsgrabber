"""
ShortsGrab core: downloading (yt-dlp) + Shorts conversion (ffmpeg).
No UI code in here, so it can be tested on its own.
"""
import os
import re
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path

import yt_dlp

# ----------------------------------------------------------------------------
# Platform definitions
# ----------------------------------------------------------------------------
PLATFORMS = {
    "youtube": {
        "label": "YouTube",
        "color": "#e53935", "hover": "#b71c1c",
        "domains": ["youtube.com", "youtu.be"],
        "hint": "Regular videos and Shorts. Playlist links grab only the linked video.",
    },
    "tiktok": {
        "label": "TikTok",
        "color": "#1fc8d6", "hover": "#138c96",
        "domains": ["tiktok.com"],
        "hint": "Usually downloads the clean (no watermark) version when TikTok offers it.",
    },
    "instagram": {
        "label": "Instagram",
        "color": "#d6249f", "hover": "#9c1a74",
        "domains": ["instagram.com"],
        "hint": "Reels and video posts. If you get a login error, set browser cookies in Settings.",
    },
    "reddit": {
        "label": "Reddit",
        "color": "#ff5700", "hover": "#c24200",
        "domains": ["reddit.com", "redd.it"],
        "hint": "Post links or v.redd.it links. Video and audio are merged automatically.",
    },
    "soundcloud": {
        "label": "SoundCloud",
        "color": "#ff5500", "hover": "#d94800",
        "domains": ["soundcloud.com", "snd.sc"],
        "hint": "Tracks, or whole playlists / albums (sets). Saved as highest-quality MP3 with tags + artwork.",
        "audio_only": True,
    },
    "twitter": {
        "label": "X",
        "color": "#1d9bf0", "hover": "#1478bd",
        "domains": ["x.com", "twitter.com", "t.co", "fixupx.com", "fxtwitter.com", "vxtwitter.com"],
        "hint": "Post links (x.com or twitter.com). Sensitive posts need browser cookies from Settings.",
    },
}

ASPECT_MODES = [
    "Blur fill 9:16",          # video centered over a blurred copy of itself
    "Crop to 9:16 (center)",   # zoom/crop to fill the frame
    "Black bars 9:16",         # letterbox
    "Original (no change)",
]
RESOLUTIONS = {
    "720 x 1280": (720, 1280),
    "1080 x 1920 (recommended)": (1080, 1920),
    "1440 x 2560": (1440, 2560),
    "2160 x 3840 (4K)": (2160, 3840),
}
QUALITY = {"Max (CRF 16)": 16, "High (CRF 18)": 18, "Balanced (CRF 21)": 21}
SPEED = {"Fast": "veryfast", "Best (slower)": "slow"}
MP3_QUALITY = {
    "320 kbps (best, CBR)": ["-b:a", "320k"],
    "V0 (~245 kbps VBR)": ["-q:a", "0"],
    "256 kbps (CBR)": ["-b:a", "256k"],
}
COOKIE_BROWSERS = ["None", "Firefox", "Chrome", "Edge", "Brave", "Opera", "Vivaldi"]

DEFAULT_SETTINGS = {
    "output_dir": str(Path.home() / "Videos" / "ShortsGrab"),
    "aspect_mode": "Blur fill 9:16",
    "resolution": "1080 x 1920 (recommended)",
    "quality": "High (CRF 18)",
    "speed": "Fast",
    "prefer_h264": False,
    "keep_original": False,
    "fps60": False,
    "cookies_browser": "None",
    "cookies_file": "",
    "mp3_quality": "320 kbps (best, CBR)",
    "mp3_ask_tags": True,
    "mp3_rename": True,
    "mp3_square_cover": True,
    "formats": {},   # per-tab choice: "Video" or "MP3"
    "name_prefix": "",  # e.g. "01 " for ranked Twitch clips
}


def cookie_opts(s):
    if s.get("cookies_file") and os.path.isfile(s["cookies_file"]):
        return {"cookiefile": s["cookies_file"]}
    if s.get("cookies_browser", "None") != "None":
        return {"cookiesfrombrowser": (s["cookies_browser"].lower(),)}
    return {}


def source_rate(path, ff=None):
    """Sample rate of the first audio stream (0 if unknown), read from ffmpeg's own stream info."""
    ff = ff or find_ffmpeg()
    try:
        r = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                           errors="replace", **_popen_kwargs())
        m = re.search(r"Stream #\S+.*?Audio:.*?(\d{4,6}) Hz", r.stderr)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def mp3_encode_args(quality="320 kbps (best, CBR)", src=None, ff=None, rate=None, pre_filter=None):
    """
    Highest-quality LAME settings:
      * 320 kbps (or V0) with the slowest, most accurate psychoacoustic model (compression_level 0 = lame -q 0)
      * 44.1/48 kHz sources keep their rate (no needless resampling);
        anything else is resampled once with the high-precision SoX resampler
      * ID3v2.3 + Xing/LAME header so players show the exact length
    """
    args = ["-c:a", "libmp3lame", *MP3_QUALITY.get(quality, MP3_QUALITY["320 kbps (best, CBR)"]),
            "-compression_level", "0", "-joint_stereo", "1"]
    if rate is None:
        rate = source_rate(src, ff) if src else 0
    out_rate = rate if rate in (44100, 48000) else 44100
    filters = [pre_filter] if pre_filter else []
    if pre_filter or rate != out_rate:   # loudnorm works at 192 kHz, so it always needs resampling back
        filters.append("aresample=resampler=soxr:precision=28")
    if filters:
        args += ["-af", ",".join(filters)]
    args += ["-ar", str(out_rate)]
    return args + ["-id3v2_version", "3", "-write_xing", "1"]


class Cancelled(Exception):
    pass


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def bundle_dirs():
    """Folders to search for bundled ffmpeg / deno (PyInstaller or next to the app)."""
    dirs = []
    if getattr(sys, "_MEIPASS", None):
        dirs.append(Path(sys._MEIPASS))
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).parent)
    dirs.append(Path(__file__).resolve().parent)
    dirs.append(Path(__file__).resolve().parent / "bin")
    return dirs


def setup_path():
    """Put bundled tools (ffmpeg, ffprobe, deno) on PATH so yt-dlp finds them."""
    for d in bundle_dirs():
        if d.exists():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")


def find_ffmpeg():
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for d in bundle_dirs():
        if (d / exe).exists():
            return str(d / exe)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def has_js_runtime():
    return any(shutil.which(x) for x in ("deno", "node", "bun"))


def detect_platform(url):
    from urllib.parse import urlparse
    try:
        host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    except ValueError:
        return None
    for key, p in PLATFORMS.items():
        if any(host == d or host.endswith("." + d) for d in p["domains"]):
            return key
    return None


def parse_time(text):
    """'83', '1:23', '1:02:03.5' -> seconds (float). Empty -> None."""
    text = (text or "").strip()
    if not text:
        return None
    if not re.fullmatch(r"\d+(:\d{1,2}){0,2}(\.\d+)?", text):
        raise ValueError(f"Bad time '{text}'. Use seconds (83) or m:ss (1:23).")
    secs = 0.0
    for part in text.split(":"):
        secs = secs * 60 + float(part)
    return secs


def _popen_kwargs():
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: no console pop-ups
    return kw


def build_filter(mode, w, h, fps60=False):
    """Return (args_list) of ffmpeg video filter arguments for the chosen mode."""
    tail = ",setsar=1,format=yuv420p" + (",fps=60" if fps60 else "")
    if mode.startswith("Crop"):
        vf = (f"crop='trunc(min(iw,ih*{w}/{h})/2)*2':'trunc(min(ih,iw*{h}/{w})/2)*2',"
              f"scale={w}:{h}:flags=lanczos" + tail)
        return ["-vf", vf]
    if mode.startswith("Black"):
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
              f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black" + tail)
        return ["-vf", vf]
    if mode.startswith("Blur"):
        sw, sh = w // 4, h // 4  # blur at low res = much faster, looks the same
        fc = (f"[0:v]split=2[bg][fg];"
              f"[bg]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
              f"boxblur=12:3,scale={w}:{h},eq=brightness=-0.07[bgb];"
              f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos[fgs];"
              f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2{tail}[v]")
        return ["-filter_complex", fc, "-map", "[v]"]
    # Original resolution, just re-encode (used when trimming in "Original" mode)
    return ["-vf", "format=yuv420p"]


# ----------------------------------------------------------------------------
# ffmpeg helpers shared by downloads and the editor tools
# ----------------------------------------------------------------------------
def probe(path, ffmpeg=None):
    """Duration / size / audio presence using `ffmpeg -i` (no ffprobe needed)."""
    ffmpeg = ffmpeg or find_ffmpeg()
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       errors="replace", **_popen_kwargs())
    out = r.stderr
    info = {"duration": 0.0, "width": 0, "height": 0, "has_audio": False, "has_video": False}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"Stream.*Video:.*?(\d{2,5})x(\d{2,5})", out)
    if m:
        info["has_video"] = True
        info["width"], info["height"] = int(m.group(1)), int(m.group(2))
    info["has_audio"] = bool(re.search(r"Stream.*Audio:", out))
    return info


def run_ffmpeg(cmd, duration, on_progress=None, cancel_flag=None):
    """Run an ffmpeg command that has `-progress pipe:1`; on_progress(fraction, seconds)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace", **_popen_kwargs())
    for line in proc.stdout:
        if cancel_flag and cancel_flag():
            proc.kill()
            raise Cancelled()
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                t = int(line.split("=")[1]) / 1_000_000
            except ValueError:
                continue
            if duration and on_progress:
                on_progress(min(max(t, 0) / duration, 1.0), t)
    err = proc.stderr.read()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed:\n" + err.strip()[-800:])


def encode_args(s):
    """Shared H.264/AAC output settings for every video the app makes."""
    return ["-c:v", "libx264", "-preset", SPEED[s["speed"]], "-crf", str(QUALITY[s["quality"]]),
            "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart"]


def shorts_cmd(ffmpeg, src, dst, s, start=None, end=None):
    """ffmpeg command converting `src` with the chosen aspect mode (optionally trimmed)."""
    w, h = RESOLUTIONS[s["resolution"]]
    cmd = [ffmpeg, "-y", "-hide_banner", "-nostats", "-loglevel", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if end is not None:
        cmd += ["-t", f"{end - (start or 0):.3f}"]
    filt = build_filter(s["aspect_mode"], w, h, s["fps60"])
    cmd += filt
    if "-map" not in filt:
        cmd += ["-map", "0:v:0"]
    cmd += ["-map", "0:a:0?", *encode_args(s), "-progress", "pipe:1", str(dst)]
    return cmd


# ----------------------------------------------------------------------------
# The job runner
# ----------------------------------------------------------------------------
class Job:
    """
    Downloads one URL and (optionally) converts it for Shorts.
    `emit(kind, payload)` is called with:
       ("log", str) ("status", str) ("progress", 0..1 float) ("done", path)
    """

    def __init__(self, url, platform, settings, emit, start=None, end=None, cancel_flag=None,
                 fmt="Video"):
        self.url = url.strip()
        self.fmt = fmt
        self.platform = platform
        self.s = {**DEFAULT_SETTINGS, **settings}
        self.emit = emit
        self.start = start
        self.end = end
        self.cancel_flag = cancel_flag or (lambda: False)
        self.ffmpeg = find_ffmpeg()

    # ---- yt-dlp ------------------------------------------------------------
    def _hook(self, d):
        if self.cancel_flag():
            raise Cancelled()
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes", 0)
            if total:
                self.emit("progress", min(done / total, 1.0) * 0.6)  # download = first 60%
            speed = d.get("speed")
            sp = f"  {speed / 1_048_576:.1f} MB/s" if speed else ""
            self.emit("status", f"Downloading{sp}")
        elif d["status"] == "finished":
            self.emit("status", "Merging video + audio...")

    def _ydl_opts(self, tmpdir):
        class Logger:
            def __init__(s, emit): s.emit = emit
            def debug(s, msg): pass
            def info(s, msg): pass
            def warning(s, msg):
                if "JavaScript runtime" in msg or "js-runtimes" in msg:
                    return  # handled with our own friendlier message
                s.emit("log", "⚠ " + msg)
            def error(s, msg): pass  # shown once by the UI when the job fails

        opts = {
            # best video + best audio, fall back to best single file
            "format": "bestvideo*+bestaudio/best",
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(tmpdir, self.s["name_prefix"].replace("%", "%%")
                                    + "%(title).70B [%(id)s].%(ext)s"),
            "noplaylist": True,
            "windowsfilenames": True,
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "logger": Logger(self.emit),
            "progress_hooks": [self._hook],
            "retries": 5,
            "fragment_retries": 5,
            "concurrent_fragment_downloads": 4,
        }
        if self.ffmpeg:
            opts["ffmpeg_location"] = self.ffmpeg
        if self.fmt == "MP3":
            opts["format"] = "bestaudio/best"     # no need to pull the video stream
            # rank by audio bitrate, then lossless/high-quality codecs, then sample rate
            opts["format_sort"] = ["abr", "acodec:flac:alac:wav:opus:aac:mp3", "asr"]
            opts.pop("merge_output_format")
            opts["writethumbnail"] = True        # becomes the cover art
            opts["outtmpl"] = {"default": opts["outtmpl"],
                               "thumbnail": os.path.join(tmpdir, "cover.%(ext)s")}
        elif self.s["prefer_h264"]:
            # most compatible codec first; still highest resolution available in it
            opts["format_sort"] = ["vcodec:h264", "res", "fps", "acodec:aac"]
        else:
            opts["format_sort"] = ["res", "fps", "vbr", "acodec"]
        opts.update(cookie_opts(self.s))
        return opts

    def download(self, tmpdir):
        with yt_dlp.YoutubeDL(self._ydl_opts(tmpdir)) as ydl:
            info = ydl.extract_info(self.url, download=True)
            if info.get("_type") == "playlist" and info.get("entries"):
                info = next(e for e in info["entries"] if e)
            path = None
            if info.get("requested_downloads"):
                path = info["requested_downloads"][0].get("filepath")
            if not path or not os.path.exists(path):
                files = sorted(Path(tmpdir).glob("*"), key=lambda p: p.stat().st_size)
                files = [f for f in files if f.suffix.lower() in
                         (".mp4", ".mkv", ".webm", ".mov", ".m4a", ".opus", ".mp3", ".ogg", ".aac")]
                path = str(files[-1]) if files else None
            if not path:
                raise RuntimeError("Download finished but no video file was found.")
            return path, info

    # ---- ffmpeg ------------------------------------------------------------
    def convert(self, src, dst, duration):
        cmd = shorts_cmd(self.ffmpeg, src, dst, self.s, self.start, self.end)
        self._ffmpeg(cmd, duration, "Converting for Shorts")

    def _ffmpeg(self, cmd, duration, label):
        def prog(f, t):
            self.emit("progress", 0.6 + 0.4 * f)
            self.emit("status", f"{label}  {int(t)}s / {int(duration)}s")
        run_ffmpeg(cmd, duration, prog, self.cancel_flag)

    def convert_mp3(self, src, dst, duration):
        cmd = [self.ffmpeg, "-y", "-hide_banner", "-nostats", "-loglevel", "error"]
        if self.start:
            cmd += ["-ss", f"{self.start:.3f}"]
        cmd += ["-i", src]
        if self.end is not None:
            cmd += ["-t", f"{self.end - (self.start or 0):.3f}"]
        cmd += ["-map", "0:a:0", "-vn", "-map_metadata", "-1", *mp3_encode_args(self.s["mp3_quality"], src,
                                                                                self.ffmpeg),
                "-progress", "pipe:1", dst]
        self._ffmpeg(cmd, duration, "Converting to MP3")

    def run_mp3(self, tmp, out_dir):
        import tags as tagmod
        self.emit("status", "Fetching audio...")
        src, info = self.download(tmp)
        title = info.get("title") or "audio"
        self.emit("log", f"Got: {title}  ({info.get('acodec', '?')}"
                         + (f", {info.get('abr'):.0f} kbps source" if info.get("abr") else "") + ")")
        full = info.get("duration") or 0
        if self.end is not None and full and self.end > full:
            self.end = None
        clip_len = (self.end if self.end is not None else full) - (self.start or 0)

        t = tagmod.guess_from_info(info, self.url)
        if self.s.get("album_override"):
            t["album"] = self.s["album_override"]
            t["albumartist"] = self.s.get("album_artist") or t["albumartist"]
            t["track"], t["tracktotal"] = str(self.s["track_no"]), str(self.s["track_total"])
        if not t.get("genre") and info.get("genres"):
            t["genre"] = info["genres"][0]
        thumbs = [p for p in Path(tmp).glob("cover.*")]
        if thumbs:
            try:
                t["cover"] = tagmod.make_cover(thumbs[0], square=self.s["mp3_square_cover"])
            except Exception as e:
                self.emit("log", f"⚠ Couldn't use thumbnail as cover: {e}")

        dst = out_dir / (tagmod.safe_name(Path(src).stem) + ".mp3")
        i = 2
        while dst.exists():
            dst = out_dir / f"{tagmod.safe_name(Path(src).stem)} ({i}).mp3"
            i += 1
        self.convert_mp3(src, str(dst), clip_len if clip_len > 0 else None)
        tagmod.write_tags(str(dst), t)          # sensible tags right away
        if self.s["mp3_rename"]:
            dst = Path(tagmod.rename_to_artist_title(str(dst), t))
        self.emit("progress", 1.0)
        self.emit("done", str(dst))
        if self.s["mp3_ask_tags"]:
            self.emit("tag", {"path": str(dst), "tags": t})
        return str(dst)

    # ---- main --------------------------------------------------------------
    def run(self):
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg not found. Install it or use the packaged .exe build.")
        if self.platform == "youtube" and not has_js_runtime():
            self.emit("log", "⚠ Deno isn't installed, so YouTube may only give lower qualities. "
                             "Install it with:  winget install DenoLand.Deno")
        out_dir = Path(self.s["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="shortsgrab_") as tmp:
            if self.fmt == "MP3":
                return self.run_mp3(tmp, out_dir)
            self.emit("status", "Fetching video info...")
            src, info = self.download(tmp)
            title = info.get("title") or "video"
            vw, vh = info.get("width"), info.get("height")
            self.emit("log", f"Got: {title}  ({vw}x{vh}" +
                      (f", {info.get('fps'):.0f}fps" if info.get("fps") else "") +
                      f", {info.get('vcodec', '?').split('.')[0]})")

            full = info.get("duration") or 0
            if self.end is not None and full and self.end > full:
                self.end = None
            clip_len = (self.end if self.end is not None else full) - (self.start or 0)

            base = Path(src).stem
            mode = self.s["aspect_mode"]
            needs_convert = not mode.startswith("Original") or self.start or self.end is not None

            if not needs_convert:  # Original mode, no trim: just hand over the file
                orig_dst = out_dir / Path(src).name
                shutil.copy2(src, orig_dst)
                self.emit("progress", 1.0)
                self.emit("done", str(orig_dst))
                return str(orig_dst)
            if self.s["keep_original"]:
                orig_dst = out_dir / Path(src).name
                shutil.copy2(src, orig_dst)
                self.emit("log", f"Saved original: {orig_dst.name}")

            suffix = "_trimmed" if mode.startswith("Original") else "_short"
            dst = out_dir / f"{base}{suffix}.mp4"
            self.emit("status", "Converting for Shorts...")
            self.convert(src, str(dst), clip_len if clip_len > 0 else None)

            if clip_len > 180:
                self.emit("log", f"ℹ Clip is {int(clip_len)}s. Shorts max out at 3 minutes, "
                                 "so set a trim if you want it to post as a Short.")
            if vh and not mode.startswith("Original"):
                tw, th = RESOLUTIONS[self.s["resolution"]]
                # the source's useful height after being fit into the 9:16 frame
                if mode.startswith("Crop") and vh < th * 0.7:
                    self.emit("log", f"ℹ Source is only {vh}p, so a 9:16 crop will look soft.")
            self.emit("progress", 1.0)
            self.emit("done", str(dst))
            return str(dst)


def friendly_error(exc, platform):
    msg = str(exc)
    msg = re.sub(r"\x1b\[[0-9;]*m", "", msg).replace("ERROR: ", "")
    low = msg.lower()
    if platform == "instagram" and ("login" in low or "rate" in low or "cookies" in low):
        msg += ("\n→ Instagram wants you logged in. In Settings, set 'Browser cookies' to the "
                "browser where you're logged into Instagram (Firefox works most reliably).")
    elif platform == "soundcloud" and ("go+" in low or "preview" in low or "snipped" in low):
        msg += ("\n→ That track is SoundCloud Go+ only, so only a 30s preview is public. Set 'Browser cookies' "
                "in Settings to a browser logged into a Go+ account to get the full track.")
    elif platform == "twitter" and ("no video" in low or "no media" in low):
        msg += "\n→ That post has no video (it may be an image or GIF-only post, or the video is in a reply)."
    elif platform == "twitter" and ("login" in low or "nsfw" in low or "sensitive" in low or "age" in low):
        msg += ("\n→ X requires you to be logged in for this post. In Settings, set 'Browser cookies' to the "
                "browser where you're logged into X (Firefox works most reliably).")
    elif "could not copy" in low and "cookie" in low:
        msg += "\n→ Close that browser completely and try again, or use Firefox / a cookies.txt file."
    elif "unsupported url" in low:
        msg += "\n→ Check the link. It should be the direct link to a single video/post."
    elif "private" in low:
        msg += "\n→ The video is private. Browser cookies from an account that can see it may help."
    elif "http error 403" in low or "unable to extract" in low:
        msg += "\n→ The site may have changed. Click 'Update downloader' in Settings and try again."
    return msg
