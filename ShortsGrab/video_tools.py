"""
Video Editor processing (no UI): gameplay split, local Shorts converter, splitter.
Every function takes emit(kind, payload) and cancel_flag() like core.Job.
"""
import math
import random
from pathlib import Path

import core

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv"}


def even(x):
    return max(2, int(round(x / 2)) * 2)


def unique_path(path):
    p = Path(path)
    i = 2
    while p.exists():
        p = p.with_name(f"{p.stem.rsplit(' (', 1)[0]} ({i}){p.suffix}")
        i += 1
    return p


def list_videos(folder):
    return sorted(str(p) for p in Path(folder).iterdir() if p.suffix.lower() in VIDEO_EXTS)


# ----------------------------------------------------------------------------
# Gameplay split (clip on top, gameplay underneath)
# ----------------------------------------------------------------------------
GP_DEFAULTS = {
    "gp_ratio": 0.5,            # fraction of the height used by the main clip
    "gp_position": "Bottom",    # where the gameplay goes
    "gp_top_fit": "Fill (crop)",
    "gp_volume": 0.0,           # gameplay audio, 0 = muted
    "gp_random_start": True,
    "gp_divider": 0,            # px of black line between the halves
    "gp_sources": [],           # gameplay files (one is picked at random per clip)
}


def _box(label_in, label_out, w, h, fit):
    """Filter fitting a stream into w x h either by crop-fill or blur-fill."""
    if fit.startswith("Fit"):
        sw, sh = even(w / 4), even(h / 4)
        return (f"[{label_in}]split=2[{label_out}b][{label_out}f];"
                f"[{label_out}b]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
                f"boxblur=10:2,scale={w}:{h},eq=brightness=-0.07[{label_out}bb];"
                f"[{label_out}f]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos[{label_out}ff];"
                f"[{label_out}bb][{label_out}ff]overlay=(W-w)/2:(H-h)/2,setsar=1[{label_out}]")
    return (f"[{label_in}]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={w}:{h},setsar=1[{label_out}]")


def gameplay_split(src, gameplay, dst, s, emit, cancel_flag, p_range=(0.0, 1.0)):
    ff = core.find_ffmpeg()
    o = {**GP_DEFAULTS, **s}
    W, H = core.RESOLUTIONS[s["resolution"]]
    a, g = core.probe(src, ff), core.probe(gameplay, ff)
    if not a["has_video"]:
        raise RuntimeError(f"{Path(src).name} has no video stream.")
    if not g["has_video"]:
        raise RuntimeError(f"Gameplay file {Path(gameplay).name} has no video stream.")
    dur = a["duration"] or 60.0

    offset = 0.0
    if o["gp_random_start"] and g["duration"] > dur + 2:
        offset = random.uniform(0, g["duration"] - dur - 1)
    loop = g["duration"] and g["duration"] < offset + dur + 0.5

    div = even(o["gp_divider"]) if o["gp_divider"] else 0
    h_main = even((H - div) * float(o["gp_ratio"]))
    h_gp = H - div - h_main
    fps = 60 if s.get("fps60") else 30

    cmd = [ff, "-y", "-hide_banner", "-nostats", "-loglevel", "error", "-i", str(src)]
    if loop:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-ss", f"{offset:.2f}", "-i", str(gameplay)]

    parts = [
        _box("0:v", "m", W, h_main, o["gp_top_fit"]),
        f"[1:v]scale={W}:{h_gp}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{h_gp},setsar=1[g]",
        f"[m]fps={fps}[m2]", f"[g]fps={fps}[g2]",
    ]
    order = ["g2", "m2"] if o["gp_position"] == "Top" else ["m2", "g2"]
    stack = [f"[{order[0]}]"]
    if div:
        parts.append(f"color=c=black:s={W}x{div}:r={fps}[d]")
        stack.append("[d]")
    stack.append(f"[{order[1]}]")
    parts.append("".join(stack) + f"vstack=inputs={len(stack)}:shortest=1,format=yuv420p[v]")

    vol = float(o["gp_volume"])
    amap = []
    if a["has_audio"] and vol > 0 and g["has_audio"]:
        parts.append(f"[0:a]aresample=48000[a0];[1:a]volume={vol:.2f},aresample=48000[a1];"
                     f"[a0][a1]amix=inputs=2:duration=first:normalize=0[a]")
        amap = ["-map", "[a]"]
    elif a["has_audio"]:
        amap = ["-map", "0:a:0"]
    elif vol > 0 and g["has_audio"]:
        parts.append(f"[1:a]volume={vol:.2f}[a]")
        amap = ["-map", "[a]"]

    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", *amap, "-t", f"{dur:.3f}",
            *core.encode_args(s), "-progress", "pipe:1", str(dst)]

    lo, hi = p_range

    def prog(f, t):
        emit("progress", lo + (hi - lo) * f)
        emit("status", f"Building split  {int(t)}s / {int(dur)}s")
    core.run_ffmpeg(cmd, dur, prog, cancel_flag)
    return str(dst)


def pick_gameplay(sources):
    files = []
    for src in sources:
        p = Path(src)
        if p.is_dir():
            files += list_videos(p)
        elif p.exists():
            files.append(str(p))
    if not files:
        raise RuntimeError("No gameplay video set. Add one in Video Editor → Gameplay Split.")
    return random.choice(files)


# ----------------------------------------------------------------------------
# Local Shorts converter
# ----------------------------------------------------------------------------
def convert_file(src, out_dir, s, emit, cancel_flag, start=None, end=None):
    ff = core.find_ffmpeg()
    info = core.probe(src, ff)
    dur = (end if end is not None else info["duration"]) - (start or 0)
    dst = unique_path(Path(out_dir) / f"{Path(src).stem}_short.mp4")

    def prog(f, t):
        emit("progress", f)
        emit("status", f"Converting  {int(t)}s / {int(dur)}s")
    core.run_ffmpeg(core.shorts_cmd(ff, src, dst, s, start, end), dur, prog, cancel_flag)
    return str(dst)


# ----------------------------------------------------------------------------
# Splitter
# ----------------------------------------------------------------------------
def split_points(duration, seg):
    """Cut points for `seg`-second parts; a tiny last bit (<5s) joins the previous part."""
    n = max(1, math.ceil(duration / seg))
    pts = [(i * seg, min((i + 1) * seg, duration)) for i in range(n)]
    if len(pts) > 1 and pts[-1][1] - pts[-1][0] < 5:
        last = pts.pop()
        pts[-1] = (pts[-1][0], last[1])
    return pts


def split_file(src, out_dir, seg, to_shorts, s, emit, cancel_flag):
    ff = core.find_ffmpeg()
    info = core.probe(src, ff)
    if not info["duration"]:
        raise RuntimeError("Couldn't read the video length.")
    pts = split_points(info["duration"], seg)
    ss = dict(s) if to_shorts else {**s, "aspect_mode": "Original (no change)"}
    folder = Path(out_dir) / f"{Path(src).stem} parts"
    folder.mkdir(parents=True, exist_ok=True)
    outs = []
    for i, (a, b) in enumerate(pts):
        dst = folder / f"{Path(src).stem} part {i + 1:02d}.mp4"
        n = len(pts)

        def prog(f, t, i=i, a=a, b=b):
            emit("progress", (i + f) / n)
            emit("status", f"Part {i + 1}/{n}  {int(t)}s / {int(b - a)}s")
        core.run_ffmpeg(core.shorts_cmd(ff, src, dst, ss, a, b), b - a, prog, cancel_flag)
        outs.append(str(dst))
        emit("log", f"  ✓ part {i + 1:02d}  ({int(a)}s → {int(b)}s)")
    return outs
