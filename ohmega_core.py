#!/usr/bin/env python3
"""Ohmega core — loudness measurement and gain application.

Pure logic with no GUI dependency, shared by the desktop app (main.py) and the
command-line tool (ohmega-cli). Only ffmpeg is required at runtime.
"""
import os
import shutil
import subprocess
from pathlib import Path

# Loudness targets (EBU R128 integrated loudness, in LUFS)
TARGETS = {
    "Streaming (-14 LUFS)": -14.0,
    "ReplayGain 2.0 (-18 LUFS)": -18.0,
    "Broadcast / Film (-23 LUFS)": -23.0,
}

CODEC_MAP = {
    # Lossless — audio data reencoded losslessly
    ".flac": ["-c:a", "flac", "-compression_level", "8"],
    ".wav":  ["-c:a", "pcm_s24le"],
    ".aiff": ["-c:a", "pcm_s24be"],
    ".aif":  ["-c:a", "pcm_s24be"],
    ".ape":  ["-c:a", "ape"],
    ".wv":   ["-c:a", "wavpack"],
    # Lossy — small quality loss on re-encode
    ".mp3":  ["-c:a", "libmp3lame", "-q:a", "0"],
    ".ogg":  ["-c:a", "libvorbis", "-q:a", "10"],
    ".opus": ["-c:a", "libopus", "-b:a", "320k"],
    ".m4a":  ["-c:a", "aac", "-b:a", "320k"],
    ".aac":  ["-c:a", "aac", "-b:a", "320k"],
    ".wma":  ["-c:a", "wmav2", "-b:a", "320k"],
    ".mpc":  ["-c:a", "libmp3lame", "-q:a", "0"],  # transcode to mp3
}

SUPPORTED_EXTENSIONS = tuple(CODEC_MAP.keys())

LOSSLESS_EXTENSIONS = {".flac", ".wav", ".aiff", ".aif", ".ape", ".wv"}

# Originals are copied here before modifying; never treat it as input.
BACKUP_DIRNAME = "Ohmega Backup"


def _parse_integrated_lufs(stderr: str):
    for line in reversed(stderr.splitlines()):
        if "I:" in line and "LUFS" in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if p == "I:":
                    return float(parts[i + 1])
    return None


def measure_lufs(filepath: str) -> float:
    result = subprocess.run(
        ["ffmpeg", "-i", filepath, "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True
    )
    lufs = _parse_integrated_lufs(result.stderr)
    if lufs is None:
        raise ValueError(f"Could not measure loudness: {filepath}")
    return lufs


def measure_album_lufs(files: list) -> float:
    """Integrated loudness of a whole folder measured as one continuous program
    (EBU R128 over all tracks concatenated) — the basis for a single album gain."""
    if len(files) == 1:
        return measure_lufs(files[0])
    inputs = []
    pre = []
    for i, f in enumerate(files):
        inputs += ["-i", f]
        # Unify rate/layout so concat accepts mixed formats inside one folder
        pre.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{i}]")
    chain = "".join(f"[a{i}]" for i in range(len(files)))
    filter_complex = (
        ";".join(pre)
        + f";{chain}concat=n={len(files)}:v=0:a=1[c];[c]ebur128=peak=true[out]"
    )
    result = subprocess.run(
        ["ffmpeg", *inputs, "-filter_complex", filter_complex,
         "-map", "[out]", "-f", "null", "-"],
        capture_output=True, text=True
    )
    lufs = _parse_integrated_lufs(result.stderr)
    if lufs is None:
        raise RuntimeError(result.stderr[-300:] or "Could not measure album loudness")
    return lufs


def apply_gain_direct(filepath: str, gain: float):
    p = Path(filepath)
    tmp = p.with_suffix(".ohmega_tmp" + p.suffix)
    ext = p.suffix.lower()
    codec = CODEC_MAP.get(ext)
    if codec is None:
        raise ValueError(f"Unsupported format: {ext}")

    result = subprocess.run(
        ["ffmpeg", "-y", "-i", filepath,
         "-af", f"volume={gain}dB",
         "-map_metadata", "0",
         *codec, str(tmp)],
        capture_output=True
    )
    if result.returncode != 0:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(result.stderr.decode()[-300:])
    tmp.replace(p)


def backup_file(filepath: str) -> str:
    p = Path(filepath)
    # Flatpak document portal paths (/run/user/…) are read-only dirs — back up to ~/Ohmega Backup instead
    if str(p).startswith("/run/user/"):
        backup_dir = Path.home() / BACKUP_DIRNAME
    else:
        backup_dir = p.parent / BACKUP_DIRNAME
    backup_dir.mkdir(exist_ok=True)
    dest = backup_dir / p.name
    if not dest.exists():
        shutil.copy2(filepath, dest)
    return str(backup_dir)


def collect_audio_files(path: str) -> list:
    """Supported audio files under *path*.

    If *path* is a folder, walk it recursively and return the sorted audio
    files inside; if it is a single supported audio file, return just that.
    """
    if os.path.isdir(path):
        out = []
        for root, dirs, fnames in os.walk(path):
            dirs[:] = [d for d in dirs if d != BACKUP_DIRNAME]  # skip our backups
            for fn in sorted(fnames):
                if fn.lower().endswith(SUPPORTED_EXTENSIONS):
                    out.append(os.path.join(root, fn))
        return out
    if path.lower().endswith(SUPPORTED_EXTENSIONS):
        return [path]
    return []
