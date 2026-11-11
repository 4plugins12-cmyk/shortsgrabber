"""
MP3 tagging for ShortsGrab, written to be read cleanly by Apple Music / iTunes:
  * ID3v2.3 (the version Apple handles best), UTF-16 text
  * front cover embedded as a baseline JPEG (APIC type 3)
  * iTunes compilation flag (TCMP), track/disc as "n/total"
"""
import io
import re
from pathlib import Path

from mutagen.id3 import (ID3, ID3NoHeaderError, TIT2, TPE1, TPE2, TALB, TCON, TDRC,
                         TRCK, TPOS, TCOM, TBPM, COMM, USLT, APIC, TCMP)
from mutagen.mp3 import MP3

try:
    from PIL import Image
except ImportError:  # app still works, cover art just isn't resized
    Image = None

FIELDS = ["title", "artist", "album", "albumartist", "genre", "year", "track", "tracktotal",
          "disc", "disctotal", "bpm", "composer", "comment", "lyrics"]

GENRES = ["Hip-Hop/Rap", "Trap", "Rap", "R&B/Soul", "Pop", "Electronic", "Dance", "House",
          "Hyperpop", "Rage", "Plugg", "Drill", "Alternative", "Indie", "Rock", "Metal",
          "Ambient", "Lo-Fi", "Jazz", "Soundtrack", "Country", "Latin", "K-Pop", "Phonk",
          "Podcast", "Other"]

_JUNK = re.compile(
    r"\s*[\(\[]\s*(official\s*)?(hd\s*|4k\s*)?(music\s*|lyric\s*)?"
    r"(video|audio|lyrics?|visuali[sz]er|mv|hd|hq|4k|clip)\s*[\)\]]", re.I)


def empty_tags():
    t = {k: "" for k in FIELDS}
    t.update(compilation=False, cover=None)
    return t


# ---------------------------------------------------------------------------
# Cover art
# ---------------------------------------------------------------------------
def make_cover(data_or_path, square=True, max_size=1400):
    """Any image (webp/png/jpg) -> baseline RGB JPEG bytes Apple Music accepts."""
    if data_or_path is None:
        return None
    raw = Path(data_or_path).read_bytes() if not isinstance(data_or_path, bytes) else data_or_path
    if Image is None:
        return raw
    im = Image.open(io.BytesIO(raw))
    im = im.convert("RGB")
    if square:
        w, h = im.size
        s = min(w, h)
        im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    if max(im.size) > max_size:
        im.thumbnail((max_size, max_size), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=92, progressive=False, optimize=True)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Guessing tags from the video info
# ---------------------------------------------------------------------------
def clean_title(t):
    t = _JUNK.sub("", t or "")
    return re.sub(r"\s{2,}", " ", t).strip(" -–")


def guess_from_info(info, url=""):
    t = empty_tags()
    raw_title = info.get("track") or info.get("title") or ""
    artist = info.get("artist") or ", ".join(info.get("artists") or []) or ""
    title = clean_title(raw_title)
    uploader = re.sub(r"\s*-\s*Topic$", "", info.get("uploader") or info.get("channel") or "").strip()
    if "|" in title:
        parts = [p.strip() for p in title.split("|") if p.strip()]
        if len(parts) >= 2 and not artist and uploader and parts[0].lower() == uploader.lower():
            artist, title = parts[0], parts[1]          # "Artist | Song"
        elif parts:
            title = parts[0]                            # "Song | channel stuff"
    if not artist:
        m = re.match(r"^(.+?)\s+[-–—]\s+(.+)$", title)
        if m:
            artist, title = m.group(1).strip(), m.group(2).strip()
        else:
            artist = info.get("uploader") or info.get("channel") or info.get("creator") or ""
    artist = re.sub(r"\s*-\s*Topic$", "", artist).strip()
    year = info.get("release_year") or (info.get("upload_date") or "")[:4]

    t.update(
        title=title,
        artist=artist,
        album=info.get("album") or title,
        albumartist=info.get("album_artist") or artist,
        genre=info.get("genre") or "",
        year=str(year or ""),
        track=str(info.get("track_number") or ""),
        comment=url,
    )
    return t


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------
def _txt(tags, key):
    f = tags.get(key)
    return str(f.text[0]) if f and f.text else ""


def _split_num(s):
    s = (s or "").strip()
    if "/" in s:
        a, b = s.split("/", 1)
        return a.strip(), b.strip()
    return s, ""


def read_tags(path):
    t = empty_tags()
    try:
        id3 = ID3(path)
    except ID3NoHeaderError:
        t["title"] = Path(path).stem
        return t
    t["title"] = _txt(id3, "TIT2")
    t["artist"] = _txt(id3, "TPE1")
    t["album"] = _txt(id3, "TALB")
    t["albumartist"] = _txt(id3, "TPE2")
    t["genre"] = _txt(id3, "TCON")
    t["year"] = (_txt(id3, "TDRC") or _txt(id3, "TYER"))[:4]
    t["track"], t["tracktotal"] = _split_num(_txt(id3, "TRCK"))
    t["disc"], t["disctotal"] = _split_num(_txt(id3, "TPOS"))
    t["bpm"] = _txt(id3, "TBPM")
    t["composer"] = _txt(id3, "TCOM")
    t["compilation"] = _txt(id3, "TCMP") == "1"
    comms = id3.getall("COMM")
    t["comment"] = str(comms[0].text[0]) if comms and comms[0].text else ""
    ly = id3.getall("USLT")
    t["lyrics"] = str(ly[0].text) if ly else ""
    pics = id3.getall("APIC")
    if pics:
        front = [p for p in pics if p.type == 3] or pics
        t["cover"] = front[0].data
    if not t["title"]:
        t["title"] = Path(path).stem
    return t


def write_tags(path, t):
    """Replace all tags in `path` with `t` (dict from empty_tags())."""
    try:
        id3 = ID3(path)
        id3.delete(path)
    except ID3NoHeaderError:
        pass
    id3 = ID3()
    enc = 1  # UTF-16 with BOM: required for non-ASCII in ID3v2.3

    def put(frame_cls, value):
        value = (value or "").strip()
        if value:
            id3.add(frame_cls(encoding=enc, text=[value]))

    put(TIT2, t.get("title"))
    put(TPE1, t.get("artist"))
    put(TALB, t.get("album"))
    put(TPE2, t.get("albumartist"))
    put(TCON, t.get("genre"))
    put(TCOM, t.get("composer"))
    if (t.get("year") or "").strip()[:4].isdigit():
        id3.add(TDRC(encoding=enc, text=[t["year"].strip()[:4]]))
    if (t.get("bpm") or "").strip().isdigit():
        id3.add(TBPM(encoding=enc, text=[t["bpm"].strip()]))
    for frame_cls, n, tot in ((TRCK, "track", "tracktotal"), (TPOS, "disc", "disctotal")):
        a, b = (t.get(n) or "").strip(), (t.get(tot) or "").strip()
        if a.isdigit():
            id3.add(frame_cls(encoding=enc, text=[f"{int(a)}/{int(b)}" if b.isdigit() else str(int(a))]))
    if t.get("compilation"):
        id3.add(TCMP(encoding=enc, text=["1"]))
    if (t.get("comment") or "").strip():
        id3.add(COMM(encoding=enc, lang="eng", desc="", text=[t["comment"].strip()]))
    if (t.get("lyrics") or "").strip():
        id3.add(USLT(encoding=enc, lang="eng", desc="", text=t["lyrics"].strip()))
    if t.get("cover"):
        id3.add(APIC(encoding=0, mime="image/jpeg", type=3, desc="", data=t["cover"]))

    id3.update_to_v23()                 # TDRC -> TYER etc. so older readers see the year
    id3.save(path, v2_version=3, v1=1)


def safe_name(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s or "").strip(" .")
    return s[:120] or "track"


def rename_to_artist_title(path, t):
    p = Path(path)
    stem = safe_name(f"{t['artist']} - {t['title']}" if t.get("artist") else t.get("title"))
    new = p.with_name(stem + p.suffix)
    if new == p:
        return str(p)
    i = 2
    while new.exists():
        new = p.with_name(f"{stem} ({i}){p.suffix}")
        i += 1
    p.rename(new)
    return str(new)


def duration_text(path):
    try:
        s = int(MP3(path).info.length)
        return f"{s // 60}:{s % 60:02d}"
    except Exception:
        return ""
