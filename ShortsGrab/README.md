# ShortsGrab

Download videos from **YouTube, TikTok, Instagram, Reddit, SoundCloud and X** and make them Shorts-ready in one click
(9:16, 1080x1920, high-quality H.264/AAC MP4).

## Get the .exe (easiest)
1. Make a new GitHub repo and upload everything in this folder (including the hidden `.github` folder).
2. Go to the **Actions** tab. The build starts automatically (or click *Run workflow*).
3. When it finishes (~3 min), open the run and download **ShortsGrab-windows** → `ShortsGrab.exe`.

ffmpeg and Deno are bundled inside, so there's nothing else to install.

## Or run from source
Install Python 3.10+, then double-click `run.bat`. For full YouTube quality also run
`winget install DenoLand.Deno` once.

## Using it
- Pick the platform tab on the left, paste one or more links (one per line), hit **Download**.
- **Trim** start/end (e.g. `0:12` → `0:47`) to cut just the part you need (single link only).
- Files go to `Videos\ShortsGrab` by default (change it in Settings).

## SoundCloud
- Paste a track link, or a playlist/album (`/sets/`) link to rip the whole thing. Sets are saved in their own
  folder with the album name, album artist and track numbers filled in.
- Go+ tracks only give a 30s preview unless you set Browser cookies to a logged-in Go+ account.

## MP3 quality
Every MP3 (downloads, SoundCloud, Audio Studio) is encoded with LAME at 320 kbps CBR using its most accurate
mode (`-q 0`). The best audio stream available is picked first. 44.1/48 kHz sources keep their sample rate,
and anything else is resampled once with the high-precision SoX resampler.

## Twitch
- Open **Sites → Twitch**, type a channel (`twitch.tv/name` or just `name`), pick the time range
  (default: last 24 hours) and how many (default: top 10), then **Find clips**.
- Clips are ranked by views. Untick any you don't want, then **Download & convert selected**.
- They're converted with your Shorts settings and saved to `Twitch\<channel> <date>\`, numbered by rank.
- No Twitch account or API key needed.

- **Output style**: Shorts (your Settings style), **Gameplay split** (clip on top, gameplay underneath,
  using the layout + gameplay files from Video Editor → Gameplay Split), or original clips.

## Video Editor
- **Gameplay Split**: add your main clips and one or more gameplay videos, pick the layout (gameplay on the
  bottom or top, clip size, crop or blur-fit, gameplay audio level, divider line) and make them all at once.
  Each clip gets a random gameplay file and start point; short gameplay loops automatically.
- **Shorts Converter**: turn videos already on your PC into 9:16 in bulk (blur fill, crop or black bars).
- **Splitter**: chop long videos into 30s / 59s / 90s / 2 min / 3 min (or custom) parts, optionally 9:16.

## MP3 Editor
- **Audio Studio** (live playback, so you hear every change as you move a slider):
  waveform with draggable trim handles, click to seek, loop, A/B bypass, stereo dB meter with clip light,
  volume, bass boost (60-150 Hz), treble, low cut, stereo width, 10-band EQ, speed (slowed / sped up),
  reverb, fade in/out and a limiter. Presets: Bass Boosted, Slowed + Reverb, Sped Up, Nightcore, Lo-Fi,
  Car Speaker, Vocal Clarity, Loud. Export to MP3 320 or WAV, optional loudness normalize (-14 LUFS),
  keeps tags + cover. Spacebar = play/pause.
- **MP3 Tagger**: see below. "Open in Audio Studio" jumps straight to editing a song.

## MP3 mode + Apple Music tagging
- Flip the **Video / MP3** switch on any platform tab, then download. You get a 320 kbps MP3 (44.1 kHz).
- A tag editor pops up pre-filled from the video: "Artist - Song (Official Video)" titles are split
  automatically, and the thumbnail becomes square cover art. Fix anything, then hit **Save tags**.
- **MP3 Tagger** tab (sidebar): open any MP3s on your PC and edit title, artist, album, album artist,
  genre, year, track/disc numbers, BPM, composer, comment, lyrics, compilation flag and cover art.
  *Apply to all* turns a list into an album (shared album info + cover, tracks numbered in list order).
- Tags are written as ID3v2.3 with UTF-16 text and an embedded JPEG front cover, which Apple Music reads best.
- Tag **before** adding files to Apple Music. It caches tags on import; if you re-tag later, select the songs
  in Apple Music, Get Info, and it'll refresh (or remove and re-add them).

## Settings
| Setting | What it does |
|---|---|
| Aspect ratio | **Blur fill** (whole video + blurred background), **Crop** (zoom to fill), **Black bars**, or **Original** |
| Resolution | 1080x1920 is the Shorts standard; 1440p/4K if your source is that sharp |
| Quality | CRF 16/18/21. Lower = better quality, bigger file |
| Encode speed | Fast, or Best (slower, a bit more efficient) |
| MP3 quality | 320 kbps CBR (default), V0 VBR, or 256 kbps |
| MP3 options | Ask for tags after each download, rename to 'Artist - Title', square-crop cover |
| Browser cookies | Needed for Instagram and private/age-gated videos. Firefox works most reliably |
| Update downloader | Sites change often. If downloads start failing, update (source) or re-run the GitHub build (.exe) |

Only download and repost content you have the rights to use (your own clips, permission, or fair use).
