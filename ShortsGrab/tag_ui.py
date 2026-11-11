"""Tag editor widgets: the reusable form, the post-download pop-up, and the MP3 Tagger tab."""
import io
import os
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

import tags as tagmod

try:
    from PIL import Image
except ImportError:
    Image = None

BG = "#0b0b0d"
CARD = "#1f2024"
MUTED = "#8b8d94"
ACCENT = "#ff2e43"
ACCENT_HOVER = "#c81f32"
GREY = "#2c2e33"
GREY_HOVER = "#3a3d44"
COVER_PX = 190


class TagEditor(ctk.CTkFrame):
    """Mp3tag-style form: cover art on the left, fields on the right."""

    def __init__(self, master, square_cover=True, **kw):
        super().__init__(master, fg_color=CARD, corner_radius=12, **kw)
        self.square_cover = square_cover
        self.cover = None
        self.original_cover = None   # e.g. the video thumbnail, to restore
        self._img_ref = None
        self.entries = {}

        self.grid_columnconfigure(1, weight=1)

        # ---- cover column
        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=0, column=0, sticky="n", padx=(16, 10), pady=16)
        self.cover_lbl = ctk.CTkLabel(left, text="No cover", width=COVER_PX, height=COVER_PX,
                                      fg_color="#151619", corner_radius=8, text_color=MUTED)
        self.cover_lbl.pack()
        self.cover_info = ctk.CTkLabel(left, text="", text_color=MUTED, font=ctk.CTkFont(size=11))
        self.cover_info.pack(pady=(4, 6))
        for text, cmd in (("Choose image…", self.pick_cover),
                          ("Restore thumbnail", self.restore_cover),
                          ("Remove cover", self.remove_cover)):
            ctk.CTkButton(left, text=text, width=COVER_PX, height=28, fg_color=GREY,
                          hover_color=GREY_HOVER, command=cmd).pack(pady=2)

        # ---- fields column
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.grid(row=0, column=1, sticky="nsew", padx=(0, 16), pady=12)
        form.grid_columnconfigure((1, 3), weight=1)

        def label(r, c, text):
            ctk.CTkLabel(form, text=text, text_color=MUTED, anchor="w", font=ctk.CTkFont(size=12)
                         ).grid(row=r, column=c, sticky="w", padx=(0 if c == 0 else 12, 8), pady=3)

        def entry(r, c, key, span=1, width=None):
            e = ctk.CTkEntry(form, width=width or 140)
            e.grid(row=r, column=c, columnspan=span, sticky="ew", pady=3)
            self.entries[key] = e

        label(0, 0, "Title");        entry(0, 1, "title", span=3)
        label(1, 0, "Artist");       entry(1, 1, "artist", span=3)
        label(2, 0, "Album");        entry(2, 1, "album", span=3)
        label(3, 0, "Album artist"); entry(3, 1, "albumartist", span=3)

        label(4, 0, "Genre")
        self.genre = ctk.CTkComboBox(form, values=tagmod.GENRES)
        self.genre.grid(row=4, column=1, sticky="ew", pady=3)
        label(4, 2, "Year");         entry(4, 3, "year")

        label(5, 0, "Track")
        tr = ctk.CTkFrame(form, fg_color="transparent")
        tr.grid(row=5, column=1, sticky="w", pady=3)
        self.entries["track"] = ctk.CTkEntry(tr, width=52); self.entries["track"].pack(side="left")
        ctk.CTkLabel(tr, text=" of ", text_color=MUTED).pack(side="left")
        self.entries["tracktotal"] = ctk.CTkEntry(tr, width=52); self.entries["tracktotal"].pack(side="left")
        label(5, 2, "Disc")
        dc = ctk.CTkFrame(form, fg_color="transparent")
        dc.grid(row=5, column=3, sticky="w", pady=3)
        self.entries["disc"] = ctk.CTkEntry(dc, width=52); self.entries["disc"].pack(side="left")
        ctk.CTkLabel(dc, text=" of ", text_color=MUTED).pack(side="left")
        self.entries["disctotal"] = ctk.CTkEntry(dc, width=52); self.entries["disctotal"].pack(side="left")

        label(6, 0, "Composer");     entry(6, 1, "composer")
        label(6, 2, "BPM");          entry(6, 3, "bpm")
        label(7, 0, "Comment");      entry(7, 1, "comment", span=3)

        self.compilation = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(form, text="Part of a compilation (various artists)", variable=self.compilation,
                        font=ctk.CTkFont(size=12)).grid(row=8, column=1, columnspan=3, sticky="w", pady=(6, 3))

        label(9, 0, "Lyrics")
        self.lyrics = ctk.CTkTextbox(form, height=70, fg_color="#151619", border_width=1,
                                     border_color="#2c2e33")
        self.lyrics.grid(row=9, column=1, columnspan=3, sticky="ew", pady=3)

    # ---- data in / out
    def set_tags(self, t, original_cover=None):
        t = {**tagmod.empty_tags(), **(t or {})}
        for k, e in self.entries.items():
            e.delete(0, "end")
            e.insert(0, str(t.get(k) or ""))
        self.genre.set(t.get("genre") or "")
        self.compilation.set(bool(t.get("compilation")))
        self.lyrics.delete("1.0", "end")
        self.lyrics.insert("1.0", t.get("lyrics") or "")
        self.original_cover = original_cover if original_cover is not None else t.get("cover")
        self.set_cover(t.get("cover"))

    def get_tags(self):
        t = tagmod.empty_tags()
        for k, e in self.entries.items():
            t[k] = e.get().strip()
        t["genre"] = self.genre.get().strip()
        t["compilation"] = self.compilation.get()
        t["lyrics"] = self.lyrics.get("1.0", "end").strip()
        t["cover"] = self.cover
        return t

    # ---- cover art
    def set_cover(self, data):
        self.cover = data
        if not data or Image is None:
            self.cover_lbl.configure(image=None, text="No cover" if not data else "Cover set")
            self._img_ref = None
            self.cover_info.configure(text="")
            return
        try:
            im = Image.open(io.BytesIO(data))
            info = f"{im.size[0]}×{im.size[1]} JPEG"
            im = im.convert("RGB")
            im.thumbnail((COVER_PX, COVER_PX))
            self._img_ref = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
            self.cover_lbl.configure(image=self._img_ref, text="")
            self.cover_info.configure(text=info)
        except Exception:
            self.cover_lbl.configure(image=None, text="Unreadable image")

    def pick_cover(self):
        f = filedialog.askopenfilename(
            title="Choose cover art",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp *.bmp"), ("All files", "*.*")])
        if f:
            try:
                self.set_cover(tagmod.make_cover(f, square=self.square_cover))
            except Exception as e:
                self.cover_info.configure(text=f"Couldn't load: {e}")

    def restore_cover(self):
        self.set_cover(self.original_cover)

    def remove_cover(self):
        self.set_cover(None)


# ---------------------------------------------------------------------------
class TagDialog(ctk.CTkToplevel):
    """Pops up after an MP3 download so you can fix the tags before importing."""

    def __init__(self, master, path, t, square_cover, rename, on_close):
        super().__init__(master)
        self.path, self.rename, self.on_close = path, rename, on_close
        self.title("Edit MP3 tags")
        self.geometry("860x600")
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self.skip)

        ctk.CTkLabel(self, text="Tag your MP3", font=ctk.CTkFont(size=22, weight="bold")
                     ).pack(anchor="w", padx=20, pady=(16, 0))
        ctk.CTkLabel(self, text=Path(path).name, text_color=MUTED).pack(anchor="w", padx=20)

        self.editor = TagEditor(self, square_cover=square_cover)
        self.editor.pack(fill="both", expand=True, padx=16, pady=12)
        self.editor.set_tags(t)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(0, 16))
        self.msg = ctk.CTkLabel(bar, text="Tip: tag before adding to Apple Music, since it caches tags on import.",
                                text_color=MUTED, font=ctk.CTkFont(size=12))
        self.msg.pack(side="left")
        ctk.CTkButton(bar, text="Save tags", width=130, height=36, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      font=ctk.CTkFont(size=14, weight="bold"), command=self.save).pack(side="right")
        ctk.CTkButton(bar, text="Keep as is", width=100, height=36, fg_color=GREY, hover_color=GREY_HOVER,
                      command=self.skip).pack(side="right", padx=8)

        self.after(150, self._focus)

    def _focus(self):
        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))

    def save(self):
        t = self.editor.get_tags()
        try:
            tagmod.write_tags(self.path, t)
            final = tagmod.rename_to_artist_title(self.path, t) if self.rename else self.path
        except Exception as e:
            self.msg.configure(text=f"Couldn't save: {e}", text_color="#ff6b6b")
            return
        self.destroy()
        self.on_close(final)

    def skip(self):
        self.destroy()
        self.on_close(None)


# ---------------------------------------------------------------------------
class TaggerPage(ctk.CTkFrame):
    """Standalone Mp3tag-style editor for any MP3s on your computer."""

    def __init__(self, master, app):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.app = app
        self.files = []
        self.rows = []
        self.current = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(self, text="MP3 Tagger", font=ctk.CTkFont(size=28, weight="bold"), text_color=ACCENT
                     ).grid(row=0, column=0, columnspan=2, sticky="w", padx=28, pady=(26, 0))
        ctk.CTkLabel(self, text="Edit tags + cover art on any MP3 so it shows up properly in Apple Music.",
                     text_color=MUTED).grid(row=1, column=0, columnspan=2, sticky="nw", padx=28, pady=(2, 12))

        # ---- file list
        left = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12, width=230)
        left.grid(row=2, column=0, sticky="ns", padx=(24, 10), pady=(0, 24))
        left.grid_propagate(False)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure((0, 1, 2), weight=1)
        for i, (text, cmd) in enumerate((("+ Files", self.add_files), ("+ Folder", self.add_folder),
                                         ("Clear", self.clear))):
            ctk.CTkButton(left, text=text, height=28, fg_color=GREY, hover_color=GREY_HOVER, command=cmd
                          ).grid(row=0, column=i, padx=(10 if i == 0 else 3, 10 if i == 2 else 3), pady=10, sticky="ew")
        self.listbox = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.listbox.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=4)
        self.count = ctk.CTkLabel(left, text="No files", text_color=MUTED, font=ctk.CTkFont(size=12))
        self.count.grid(row=2, column=0, columnspan=3, pady=6)

        # ---- editor
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=2, column=1, sticky="nsew", padx=(0, 24), pady=(0, 24))
        right.grid_columnconfigure(0, weight=1)
        self.editor = TagEditor(right, square_cover=app.settings.get("mp3_square_cover", True))
        self.editor.grid(row=0, column=0, sticky="new")

        bar = ctk.CTkFrame(right, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.rename = ctk.BooleanVar(value=app.settings.get("mp3_rename", True))
        ctk.CTkCheckBox(bar, text="Rename file to 'Artist - Title'", variable=self.rename,
                        font=ctk.CTkFont(size=12)).pack(side="left")
        ctk.CTkButton(bar, text="Save", width=110, height=34, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      font=ctk.CTkFont(size=14, weight="bold"), command=self.save_current).pack(side="right")
        ctk.CTkButton(bar, text="Open in Audio Studio", width=150, height=34, fg_color=GREY,
                      hover_color=GREY_HOVER, command=self.to_studio).pack(side="right", padx=8)

        bulk = ctk.CTkFrame(right, fg_color=CARD, corner_radius=12)
        bulk.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(bulk, text="Whole list (album mode)", font=ctk.CTkFont(size=13, weight="bold")
                     ).pack(anchor="w", padx=14, pady=(10, 0))
        ctk.CTkLabel(bulk, text="Copies Album, Album artist, Genre, Year, Disc, Compilation and cover from the form "
                                "to every file in the list. Track numbers follow the list order.",
                     text_color=MUTED, font=ctk.CTkFont(size=12), wraplength=480, justify="left"
                     ).pack(anchor="w", padx=14)
        row = ctk.CTkFrame(bulk, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)
        self.autonum = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(row, text="Auto-number tracks", variable=self.autonum, font=ctk.CTkFont(size=12)
                        ).pack(side="left")
        ctk.CTkButton(row, text="Apply to all", width=120, fg_color=GREY, hover_color=GREY_HOVER,
                      command=self.apply_all).pack(side="right")
        self.status = ctk.CTkLabel(right, text="", text_color=MUTED)
        self.status.grid(row=3, column=0, sticky="w", pady=(8, 0))

    # ---- list management
    def add_paths(self, paths):
        for p in paths:
            p = str(Path(p))
            if p.lower().endswith(".mp3") and p not in self.files and os.path.exists(p):
                self.files.append(p)
        self.redraw()
        if self.current is None and self.files:
            self.select(self.files[0])

    def add_files(self):
        fs = filedialog.askopenfilenames(title="Choose MP3s", filetypes=[("MP3", "*.mp3")],
                                         initialdir=self.app.settings.get("output_dir"))
        self.add_paths(fs)

    def add_folder(self):
        d = filedialog.askdirectory(initialdir=self.app.settings.get("output_dir"))
        if d:
            self.add_paths(sorted(str(p) for p in Path(d).glob("*.mp3")))

    def clear(self):
        self.files, self.current = [], None
        self.editor.set_tags(tagmod.empty_tags())
        self.redraw()

    def redraw(self):
        for r in self.rows:
            r.destroy()
        self.rows = []
        for i, p in enumerate(self.files):
            sel = p == self.current
            b = ctk.CTkButton(self.listbox, text=f"{i + 1:>2}. {Path(p).stem}", anchor="w", height=30,
                              fg_color=ACCENT if sel else "transparent",
                              hover_color=ACCENT_HOVER if sel else GREY_HOVER,
                              text_color="white" if sel else "#d9dadd", font=ctk.CTkFont(size=12),
                              command=lambda p=p: self.select(p))
            b.pack(fill="x", pady=1)
            self.rows.append(b)
        n = len(self.files)
        self.count.configure(text=f"{n} file{'s' if n != 1 else ''}" if n else "No files")

    def select(self, path):
        self.current = path
        try:
            self.editor.set_tags(tagmod.read_tags(path))
            self.status.configure(text=f"{Path(path).name}   {tagmod.duration_text(path)}", text_color=MUTED)
        except Exception as e:
            self.status.configure(text=f"Couldn't read tags: {e}", text_color="#ff6b6b")
        self.redraw()

    def to_studio(self):
        if self.current:
            self.app.studio.load(self.current)
            self.app.show("studio")

    # ---- saving
    def save_current(self):
        if not self.current:
            self.status.configure(text="Add an MP3 first.", text_color=MUTED)
            return
        t = self.editor.get_tags()
        try:
            tagmod.write_tags(self.current, t)
            new = tagmod.rename_to_artist_title(self.current, t) if self.rename.get() else self.current
            self.files[self.files.index(self.current)] = new
            self.current = new
            self.redraw()
            self.status.configure(text=f"✓ Saved  {Path(new).name}", text_color="#5fd38d")
        except Exception as e:
            self.status.configure(text=f"Couldn't save: {e}", text_color="#ff6b6b")

    def apply_all(self):
        if not self.files:
            return
        form = self.editor.get_tags()
        shared = ("album", "albumartist", "genre", "year", "disc", "disctotal", "compilation", "cover")
        total = len(self.files)
        errors = 0
        for i, p in enumerate(self.files):
            try:
                t = tagmod.read_tags(p)
                for k in shared:
                    t[k] = form[k]
                if self.autonum.get():
                    t["track"], t["tracktotal"] = str(i + 1), str(total)
                tagmod.write_tags(p, t)
            except Exception:
                errors += 1
        if self.current:
            self.select(self.current)
        msg = f"✓ Updated {total - errors} of {total} files"
        self.status.configure(text=msg + (f"  ({errors} failed)" if errors else ""),
                              text_color="#5fd38d" if not errors else "#ffb84d")
