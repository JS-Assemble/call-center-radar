#!/usr/bin/env python
"""Downloads a portable ffmpeg build into tools/ffmpeg/ — no system PATH
edits, no admin rights, no terminal restart needed. config.py automatically
finds it there once it exists.

This is the reason PATH-based ffmpeg installs cause so much friction: every
terminal window/VS Code session caches PATH at the moment it started, so a
"restart your terminal" step is genuinely required and easy to miss. A
project-local binary sidesteps that entirely.

Usage: python scripts/setup_ffmpeg.py
"""
import platform
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = PROJECT_ROOT / "tools" / "ffmpeg"

# Static, no-installer Windows build (gyan.dev) — same builds winget's
# Gyan.FFmpeg package installs, just placed inside the project instead of
# AppData.
FFMPEG_WIN_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def _progress(block_num: int, block_size: int, total_size: int) -> None:
    if total_size <= 0:
        return
    downloaded = block_num * block_size
    pct = min(100, downloaded * 100 // total_size)
    if block_num % 100 == 0 or pct == 100:
        print(f"  downloading: {pct}%", end="\r")


def main() -> None:
    if platform.system() != "Windows":
        print(
            "This script targets Windows. On macOS/Linux, install ffmpeg with "
            "your package manager instead (brew install ffmpeg / apt-get install ffmpeg) "
            "— it'll already be on PATH and config.py will find it there."
        )
        sys.exit(0)

    exe_path = TOOLS_DIR / "bin" / "ffmpeg.exe"
    if exe_path.exists():
        print(f"ffmpeg already set up at {exe_path}")
        return

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = PROJECT_ROOT / "_ffmpeg_download.zip"

    print("Downloading ffmpeg (this is a one-time ~80MB download) ...")
    urlretrieve(FFMPEG_WIN_URL, zip_path, reporthook=_progress)
    print()

    print("Extracting ...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(PROJECT_ROOT / "_ffmpeg_extract_tmp")

    # The zip contains one top-level folder like "ffmpeg-7.0-essentials_build/"
    # with bin/, doc/, presets/ inside — move just what's needed and drop the rest.
    extracted_root = next((PROJECT_ROOT / "_ffmpeg_extract_tmp").iterdir())
    shutil.move(str(extracted_root / "bin"), str(TOOLS_DIR / "bin"))
    shutil.rmtree(PROJECT_ROOT / "_ffmpeg_extract_tmp")
    zip_path.unlink()

    print(f"Done. ffmpeg is ready at {exe_path}")
    print("No PATH changes or terminal restart needed — the app finds it automatically.")


if __name__ == "__main__":
    main()