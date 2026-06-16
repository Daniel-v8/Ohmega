# Ohmega

Normalize audio loudness for FLAC, MP3, WAV, OGG, OPUS, M4A and more — directly in the file, no player configuration needed.

## Features

- Drag & drop files or folders
- Measures loudness using EBU R128 standard (ffmpeg)
- Normalizes directly in the audio file — works in every player
- Automatic backup of originals before modifying
- Supports lossless (FLAC, WAV, AIFF, APE, WavPack) and lossy formats (MP3, OGG, OPUS, M4A, AAC, WMA)
- Three loudness targets: Streaming (−14 LUFS), ReplayGain (−18 LUFS), Broadcast / Film (−23 LUFS)
- Album gain — one shared gain per folder, keeping the loudness balance between tracks intact (EBU R128 album mode, works across multiple folders at once)
- Command-line version (`ohmega-cli`) with full feature parity, for scripting and batch jobs

## Requirements

- Python 3.12+
- ffmpeg
- PyQt6 (desktop app only — the CLI needs just Python and ffmpeg)

```bash
pip install PyQt6
```

## Run

Desktop app:

```bash
python3 main.py
```

## Command line

`ohmega-cli` shares the same engine as the app and only needs Python + ffmpeg.

```bash
# Normalize individual files to the default Streaming target (−14 LUFS)
python3 cli.py song.flac other.mp3

# Pick a target preset: streaming | replaygain | broadcast
python3 cli.py -t broadcast ~/Music

# Treat each folder as one album (a single shared gain across its tracks)
python3 cli.py --album ~/Music/Album1 ~/Music/Album2

# Preview the gain without changing anything
python3 cli.py --dry-run ~/Music

# Custom target, no backup
python3 cli.py --lufs -16 --no-backup song.flac
```

Folders are scanned recursively. Originals are backed up to an `Ohmega Backup/`
folder before modifying (disable with `--no-backup`). Run `python3 cli.py --help`
for the full list of options. When installed from a package, the command is
available simply as `ohmega-cli`.

## License

MIT
