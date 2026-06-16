#!/usr/bin/env python3
"""Ohmega CLI — normalize audio loudness directly in your files (EBU R128 / LUFS).

A terminal front-end sharing the same engine as the desktop app (ohmega_core).
Only ffmpeg is required at runtime.
"""
import argparse
import os
import sys
from pathlib import Path

# Allow running both from source and when installed next to ohmega_core.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ohmega_core import (  # noqa: E402
    SUPPORTED_EXTENSIONS,
    measure_lufs, measure_album_lufs, apply_gain_direct, backup_file,
    collect_audio_files,
)

VERSION = "1.3.0"

PRESETS = {
    "streaming": -14.0,    # Spotify/YouTube/Apple-style
    "replaygain": -18.0,   # ReplayGain 2.0
    "broadcast": -23.0,    # EBU R128 broadcast / film
}

SKIP_THRESHOLD = 0.5  # dB; below this the file is already on target


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ohmega-cli",
        description="Normalize audio loudness directly in your files (EBU R128 / LUFS). "
                    "The gain is written into the audio data, so every player plays at "
                    "the right volume — no ReplayGain tags needed.",
        epilog="Examples:\n"
               "  ohmega-cli song.flac other.mp3\n"
               "  ohmega-cli -t broadcast --dry-run ~/Music\n"
               "  ohmega-cli --album ~/Music/Album1 ~/Music/Album2\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("paths", nargs="+", metavar="PATH",
                   help="audio files or folders (folders are scanned recursively)")
    p.add_argument("-t", "--target", choices=list(PRESETS), default="streaming",
                   help="loudness target preset (default: streaming, -14 LUFS)")
    p.add_argument("-l", "--lufs", type=float, metavar="LUFS",
                   help="custom target loudness in LUFS (overrides --target)")
    p.add_argument("-a", "--album", action="store_true",
                   help="treat each folder as one album: a single shared gain measured "
                        "across all its tracks, keeping the balance between songs intact")
    p.add_argument("--backup", dest="backup", action="store_true", default=True,
                   help="back up originals to 'Ohmega Backup/' before modifying (default)")
    p.add_argument("--no-backup", dest="backup", action="store_false",
                   help="do not back up originals")
    p.add_argument("-n", "--dry-run", action="store_true",
                   help="measure and show the gain that would be applied; change nothing")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="only print warnings and errors")
    p.add_argument("--version", action="version", version=f"ohmega-cli {VERSION}")
    return p


def gather(paths, album):
    """Resolve input paths into (tracks, albums).

    tracks: list of files normalized individually (per-track).
    albums: dict {folder: [files]} — one shared album gain each (only when --album).
    """
    tracks, albums, seen = [], {}, set()
    for raw in paths:
        path = os.path.abspath(os.path.expanduser(raw))
        if not os.path.exists(path):
            print(f"warning: not found: {raw}", file=sys.stderr)
            continue
        if os.path.isdir(path):
            files = collect_audio_files(path)
            if not files:
                print(f"warning: no supported audio in: {raw}", file=sys.stderr)
                continue
            for f in files:
                if f in seen:
                    continue
                seen.add(f)
                if album:
                    albums.setdefault(str(Path(f).parent), []).append(f)
                else:
                    tracks.append(f)
        else:
            if path in seen:
                continue
            if not path.lower().endswith(SUPPORTED_EXTENSIONS):
                print(f"warning: unsupported file: {raw}", file=sys.stderr)
                continue
            seen.add(path)
            tracks.append(path)
    return tracks, albums


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    target = args.lufs if args.lufs is not None else PRESETS[args.target]
    tracks, albums = gather(args.paths, args.album)
    total = len(tracks) + sum(len(v) for v in albums.values())
    if total == 0:
        print("Nothing to do — no supported audio files.", file=sys.stderr)
        return 1

    def log(*a):
        if not args.quiet:
            print(*a)

    notes = []
    if args.dry_run:
        notes.append("dry run")
    if not args.backup and not args.dry_run:
        notes.append("no backup")
    suffix = f"  ({', '.join(notes)})" if notes else ""
    log(f"Target: {target:.1f} LUFS{suffix}")

    done = errors = 0

    # Albums — one shared gain per folder
    for folder, files in albums.items():
        name = Path(folder).name or folder
        try:
            lufs = measure_album_lufs(files)
        except Exception as e:
            print(f"[album] {name}: error measuring: {e}", file=sys.stderr)
            errors += 1
            continue
        gain = target - lufs
        log(f"\n[album] {name} — {len(files)} track(s): {lufs:.1f} LUFS -> gain {gain:+.1f} dB")
        if abs(gain) < SKIP_THRESHOLD:
            log("  already on target — skipped")
            continue
        for f in files:
            if args.dry_run:
                log(f"  would apply {gain:+.1f} dB  {Path(f).name}")
                continue
            try:
                if args.backup:
                    backup_file(f)
                apply_gain_direct(f, gain)
                done += 1
                log(f"  {gain:+.1f} dB  {Path(f).name}")
            except Exception as e:
                print(f"  error: {Path(f).name}: {e}", file=sys.stderr)
                errors += 1

    # Tracks — per-file gain
    for f in tracks:
        try:
            lufs = measure_lufs(f)
        except Exception as e:
            print(f"{Path(f).name}: error measuring: {e}", file=sys.stderr)
            errors += 1
            continue
        gain = target - lufs
        if abs(gain) < SKIP_THRESHOLD:
            log(f"{Path(f).name}: {lufs:.1f} LUFS -> on target, skipped")
            continue
        if args.dry_run:
            log(f"{Path(f).name}: {lufs:.1f} LUFS -> would apply {gain:+.1f} dB")
            continue
        try:
            if args.backup:
                backup_file(f)
            apply_gain_direct(f, gain)
            done += 1
            log(f"{Path(f).name}: {lufs:.1f} LUFS -> {gain:+.1f} dB OK")
        except Exception as e:
            print(f"error: {Path(f).name}: {e}", file=sys.stderr)
            errors += 1

    if args.dry_run:
        log(f"\nDry run complete — {total} file(s) analyzed.")
    else:
        tail = ", ".join(filter(None, [
            f"{done} file(s) normalized",
            f"{errors} error(s)" if errors else "",
            "backups created" if args.backup and done else "",
        ]))
        log(f"\nDone — {tail}.")
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
