@echo off
REM Run ShortsGrab from source (needs Python 3.10+ installed).
cd /d "%~dp0"
python -m pip install -q -U -r requirements.txt
where deno >nul 2>nul || echo [tip] For best YouTube quality install Deno:  winget install DenoLand.Deno
where ffmpeg >nul 2>nul || echo [info] ffmpeg not on PATH - using the bundled imageio-ffmpeg copy.
start "" pythonw app.py
