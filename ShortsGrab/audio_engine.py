"""
Audio Studio engine: real-time DSP used for both live playback and export,
so what you hear is exactly what gets saved.

Chain:  source (+ reverb wet) → speed (pitch follows, "slowed"/"sped up")
        → fades → low cut → bass shelf → 10-band EQ → treble shelf
        → volume → limiter → meter
"""
import math
import subprocess
import threading

import numpy as np
from scipy.signal import sosfilt, oaconvolve, lfilter

import core

try:
    import sounddevice as sd
except Exception:  # PortAudio missing: export still works, playback doesn't
    sd = None

EQ_FREQS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
EQ_LABELS = ["31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
LOWCUT = {"Off": 0, "30 Hz": 30, "60 Hz": 60, "100 Hz": 100, "150 Hz": 150}
BASS_FREQS = {"60 Hz": 60, "80 Hz": 80, "100 Hz": 100, "150 Hz": 150}

DEFAULTS = {
    "volume_db": 0.0, "bass_db": 0.0, "bass_freq": 80, "treble_db": 0.0, "lowcut": 0,
    "eq": [0.0] * 10, "speed": 1.0, "reverb_mix": 0.0, "reverb_size": 2.0,
    "fade_in": 0.0, "fade_out": 0.0, "limiter": True, "bypass": False, "width": 1.0,
}

PRESETS = {
    "Flat": {},
    "Bass Boosted": {"bass_db": 10.0, "bass_freq": 60, "eq": [3, 2, 0, -1, -1, 0, 0, 1, 1, 0], "volume_db": -1.0},
    "Slowed + Reverb": {"speed": 0.85, "reverb_mix": 0.45, "reverb_size": 3.0, "bass_db": 3.0,
                        "treble_db": -2.0},
    "Sped Up": {"speed": 1.25, "treble_db": 1.5},
    "Nightcore": {"speed": 1.35, "treble_db": 2.0, "bass_db": 2.0},
    "Lo-Fi": {"speed": 0.95, "lowcut": 100, "treble_db": -9.0, "eq": [0, 0, 1, 2, 2, 0, -2, -4, -6, -8],
              "reverb_mix": 0.15, "reverb_size": 1.2},
    "Car Speaker": {"lowcut": 30, "bass_db": 7.0, "bass_freq": 60, "eq": [4, 3, 0, -2, -1, 0, 1, 2, 2, 1]},
    "Vocal Clarity": {"lowcut": 100, "eq": [0, 0, -1, -2, -1, 1, 3, 3, 2, 1]},
    "Loud": {"volume_db": 6.0, "bass_db": 2.0, "eq": [1, 1, 0, 0, 0, 0, 1, 1, 1, 0]},
}


def db2lin(db):
    return 10.0 ** (db / 20.0)


def lin2db(x):
    return 20.0 * math.log10(max(x, 1e-9))


# ----------------------------------------------------------------------------
# RBJ cookbook biquads -> SOS rows [b0 b1 b2 a0 a1 a2] (normalised)
# ----------------------------------------------------------------------------
IDENT = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]


def _norm(b0, b1, b2, a0, a1, a2):
    return [b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]


def peaking(f, gain_db, q, sr):
    if abs(gain_db) < 0.05 or f >= sr / 2:
        return IDENT
    A = 10 ** (gain_db / 40)
    w = 2 * math.pi * f / sr
    al = math.sin(w) / (2 * q)
    c = math.cos(w)
    return _norm(1 + al * A, -2 * c, 1 - al * A, 1 + al / A, -2 * c, 1 - al / A)


def shelf(f, gain_db, sr, high=False):
    if abs(gain_db) < 0.05 or f >= sr / 2:
        return IDENT
    A = 10 ** (gain_db / 40)
    w = 2 * math.pi * f / sr
    c, s = math.cos(w), math.sin(w)
    al = s / 2 * math.sqrt(2)  # slope S = 1
    k = 2 * math.sqrt(A) * al
    if not high:
        return _norm(A * ((A + 1) - (A - 1) * c + k), 2 * A * ((A - 1) - (A + 1) * c),
                     A * ((A + 1) - (A - 1) * c - k),
                     (A + 1) + (A - 1) * c + k, -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - k)
    return _norm(A * ((A + 1) + (A - 1) * c + k), -2 * A * ((A - 1) + (A + 1) * c),
                 A * ((A + 1) + (A - 1) * c - k),
                 (A + 1) - (A - 1) * c + k, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - k)


def highpass(f, sr, q=0.7071):
    if not f:
        return IDENT
    w = 2 * math.pi * f / sr
    c, al = math.cos(w), math.sin(w) / (2 * q)
    return _norm((1 + c) / 2, -(1 + c), (1 + c) / 2, 1 + al, -2 * c, 1 - al)


def design(p, sr):
    rows = [highpass(p["lowcut"], sr), highpass(p["lowcut"], sr),        # 24 dB/oct low cut
            shelf(p["bass_freq"], p["bass_db"], sr)]
    rows += [peaking(f, g, 1.41, sr) for f, g in zip(EQ_FREQS, p["eq"])]
    rows.append(shelf(9000, p["treble_db"], sr, high=True))
    return np.array(rows, dtype=np.float64)


# ----------------------------------------------------------------------------
class PlayState:
    """Everything that changes while rendering, kept separate so export doesn't disturb playback."""

    def __init__(self, pos, n_sections):
        self.pos = float(pos)
        self.zi = np.zeros((n_sections, 2, 2))
        self.gain = 1.0
        self.sos_ver = -1
        self.sos = None


class AudioEngine:
    N_SECTIONS = 14

    def __init__(self):
        self.sr = 44100
        self.data = None          # (N, 2) float32
        self.wet = None           # reverb render, same shape
        self.wet_size = None
        self.env = None           # waveform envelope for drawing
        self.path = None
        self.params = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
        self.ver = 0
        self.trim = (0, 0)
        self.loop = False
        self.playing = False
        self.stream = None
        self.state = None
        self.meter = [0.0, 0.0, 0.0, 0.0]  # peakL peakR rmsL rmsR (linear)
        self.status_cb = None
        self._lock = threading.Lock()
        self._reverb_job = 0

    # ---- loading --------------------------------------------------------
    @staticmethod
    def device_rate():
        try:
            return int(sd.query_devices(kind="output")["default_samplerate"])
        except Exception:
            return 44100

    def load(self, path):
        self.stop()
        sr = self.device_rate() if sd else 44100
        ff = core.find_ffmpeg()
        r = subprocess.run([ff, "-v", "error", "-i", str(path), "-vn", "-f", "f32le", "-ac", "2",
                            "-ar", str(sr), "pipe:1"], capture_output=True, **core._popen_kwargs())
        if r.returncode != 0 or not r.stdout:
            raise RuntimeError("Couldn't decode that file:\n" + r.stderr.decode(errors="replace")[-400:])
        data = np.frombuffer(r.stdout, dtype=np.float32).reshape(-1, 2).copy()
        if len(data) < sr // 10:
            raise RuntimeError("That file is too short.")
        self.sr, self.data, self.path = sr, data, str(path)
        self.wet, self.wet_size = None, None
        self.trim = (0, len(data))
        self.state = PlayState(0, self.N_SECTIONS)
        bins = 3000
        mono = np.abs(data).max(axis=1)
        step = max(1, len(mono) // bins)
        n = len(mono) // step
        self.env = mono[: n * step].reshape(n, step).max(axis=1)
        if self.params["reverb_mix"] > 0:
            self.render_reverb()

    @property
    def duration(self):
        return 0 if self.data is None else len(self.data) / self.sr

    # ---- parameters -----------------------------------------------------
    def set(self, name, value):
        p = dict(self.params)
        p[name] = value
        self.params = p
        self.ver += 1
        if name in ("reverb_size", "reverb_mix") and p["reverb_mix"] > 0:
            if self.wet is None or self.wet_size != p["reverb_size"]:
                self.render_reverb()

    def set_eq(self, band, gain):
        eq = list(self.params["eq"])
        eq[band] = gain
        self.set("eq", eq)

    def apply_preset(self, name):
        p = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
        p["limiter"] = self.params["limiter"]
        p.update({k: (list(v) if isinstance(v, list) else v) for k, v in PRESETS[name].items()})
        self.params = p
        self.ver += 1
        if p["reverb_mix"] > 0 and (self.wet is None or self.wet_size != p["reverb_size"]):
            self.render_reverb()

    # ---- reverb (rendered in the background, mixed live) ----------------
    def render_reverb(self):
        if self.data is None:
            return
        self._reverb_job += 1
        job = self._reverb_job
        size = self.params["reverb_size"]
        data, sr = self.data, self.sr
        if self.status_cb:
            self.status_cb("Rendering reverb…")

        def work():
            rng = np.random.default_rng(7)
            n = int(size * sr)
            t = np.arange(n) / sr
            env = 10 ** (-3 * t / size)                        # -60 dB at `size` seconds
            ir = rng.standard_normal((n, 2)) * env[:, None]
            ir = lfilter([0.35], [1, -0.65], ir, axis=0)       # darker, smoother tail
            pre = int(0.025 * sr)
            ir = np.vstack([np.zeros((pre, 2)), ir])
            ir /= np.sqrt((ir ** 2).sum(axis=0))
            wet = np.empty_like(data)
            for ch in range(2):
                wet[:, ch] = oaconvolve(data[:, ch], ir[:, ch].astype(np.float32))[: len(data)]
            if job == self._reverb_job and data is self.data:
                self.wet, self.wet_size = wet.astype(np.float32), size
                if self.status_cb:
                    self.status_cb("")
        threading.Thread(target=work, daemon=True).start()

    # ---- rendering ------------------------------------------------------
    def render(self, st, n, loop):
        """Render n output frames from state st. Returns (block, frames_valid, finished)."""
        p, data, sr = self.params, self.data, self.sr
        start, end = self.trim
        sp = float(p["speed"])
        idx = st.pos + np.arange(n) * sp
        if loop:
            length = max(end - start, 2)
            idx = start + np.mod(idx - start, length)
            valid = n
            finished = False
        else:
            valid = int(np.searchsorted(idx, end - 1))
            finished = valid < n
        idx = np.clip(idx, 0, len(data) - 2)
        i0 = idx.astype(np.int64)
        fr = (idx - i0).astype(np.float32)[:, None]
        x = data[i0] * (1 - fr) + data[i0 + 1] * fr

        if not p["bypass"]:
            wet, mix = self.wet, p["reverb_mix"]
            if wet is not None and mix > 0 and len(wet) == len(data):
                w = wet[i0] * (1 - fr) + wet[i0 + 1] * fr
                x = x * (1 - 0.35 * mix) + w * (mix * 1.1)
            if p["fade_in"] > 0 or p["fade_out"] > 0:
                g = np.ones(n, dtype=np.float32)
                if p["fade_in"] > 0:
                    g *= np.clip((idx - start) / (p["fade_in"] * sr), 0, 1)
                if p["fade_out"] > 0:
                    g *= np.clip((end - idx) / (p["fade_out"] * sr), 0, 1)
                x = x * g[:, None]
            if p["width"] != 1.0:
                mid = (x[:, 0] + x[:, 1]) * 0.5
                side = (x[:, 0] - x[:, 1]) * 0.5 * p["width"]
                x = np.stack([mid + side, mid - side], axis=1)
            if st.sos_ver != self.ver:
                st.sos = design(p, sr)
                st.sos_ver = self.ver
            x, st.zi = sosfilt(st.sos, x, axis=0, zi=st.zi)
            x = x * db2lin(p["volume_db"])
            if p["limiter"]:
                peak = float(np.abs(x).max()) if n else 0.0
                target = min(1.0, 0.966 / peak) if peak > 0 else 1.0     # -0.3 dBFS ceiling
                if target < st.gain:
                    st.gain = target                                       # instant attack
                    x = x * st.gain
                else:
                    new = st.gain + (target - st.gain) * min(1.0, n / (0.25 * sr))  # ~250 ms release
                    x = x * np.linspace(st.gain, new, n)[:, None]
                    st.gain = new
        if valid < n:
            x[valid:] = 0
        pk = np.abs(x).max(axis=0) if n else np.zeros(2)
        rms = np.sqrt((x ** 2).mean(axis=0)) if n else np.zeros(2)
        x = np.clip(x, -1.0, 1.0).astype(np.float32)
        last = st.pos + n * sp
        st.pos = start + (last - start) % max(end - start, 2) if loop else last
        return x, valid, finished, (pk, rms)

    # ---- live playback --------------------------------------------------
    def _callback(self, outdata, frames, time_info, status):
        try:
            x, valid, finished, (pk, rms) = self.render(self.state, frames, self.loop)
        except Exception:
            outdata[:] = 0
            raise sd.CallbackStop
        outdata[:] = x
        self.meter = [float(pk[0]), float(pk[1]), float(rms[0]), float(rms[1])]
        if finished:
            self.playing = False
            self.state.pos = self.trim[0]
            raise sd.CallbackStop

    def play(self):
        if self.data is None:
            return "Load a file first."
        if sd is None:
            return "No audio output available (PortAudio missing). Export still works."
        if self.playing:
            return None
        s, e = self.trim
        if not (s <= self.state.pos < e - 1):
            self.state.pos = s
        try:
            self.stream = sd.OutputStream(samplerate=self.sr, channels=2, dtype="float32",
                                          blocksize=1024, latency="low", callback=self._callback,
                                          finished_callback=self._finished)
            self.stream.start()
            self.playing = True
        except Exception as ex:
            self.stream = None
            return f"Couldn't open the audio device: {ex}"
        return None

    def _finished(self):
        self.playing = False
        self.meter = [0.0, 0.0, 0.0, 0.0]

    def pause(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
        self.stream = None
        self.playing = False
        self.meter = [0.0, 0.0, 0.0, 0.0]

    def stop(self):
        self.pause()
        if self.state is not None:
            self.state.pos = self.trim[0]

    def seek(self, seconds):
        if self.state is not None:
            self.state.pos = float(np.clip(seconds * self.sr, 0, len(self.data) - 2))

    @property
    def position(self):
        return 0 if self.state is None else self.state.pos / self.sr

    # ---- export ---------------------------------------------------------
    def export(self, dst, fmt="MP3 320 kbps", normalize=False, progress=None, cancel=None):
        if self.data is None:
            raise RuntimeError("Nothing loaded.")
        ff = core.find_ffmpeg()
        st = PlayState(self.trim[0], self.N_SECTIONS)
        sp = self.params["speed"]
        total = int((self.trim[1] - self.trim[0]) / sp)
        cmd = [ff, "-y", "-v", "error", "-f", "f32le", "-ar", str(self.sr), "-ac", "2", "-i", "pipe:0"]
        norm = "loudnorm=I=-14:TP=-1:LRA=11" if normalize else None
        if fmt.startswith("MP3"):
            cmd += core.mp3_encode_args(rate=self.sr, pre_filter=norm)
        else:
            out_rate = self.sr if self.sr in (44100, 48000) else 44100
            filters = [norm] if norm else []
            if norm or out_rate != self.sr:
                filters.append("aresample=resampler=soxr:precision=28:dither_method=triangular")
            if filters:
                cmd += ["-af", ",".join(filters)]
            cmd += ["-c:a", "pcm_s24le" if "24" in fmt else "pcm_s16le", "-ar", str(out_rate)]
        cmd.append(str(dst))
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, **core._popen_kwargs())
        done = 0
        try:
            while done < total:
                if cancel and cancel():
                    proc.kill()
                    raise core.Cancelled()
                n = min(16384, total - done)
                x, valid, finished, _ = self.render(st, n, False)
                proc.stdin.write(x[:valid].tobytes())
                done += n
                if progress:
                    progress(done / total)
                if finished:
                    break
            proc.stdin.close()
        except BrokenPipeError:
            pass
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError("Export failed:\n" + err[-500:])
        return str(dst)
