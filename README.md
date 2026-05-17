# Ohmega

Normalize audio loudness for FLAC, MP3, WAV, OGG, OPUS, M4A and more — directly in the file, no player configuration needed.

## Features

- Drag & drop files or folders
- Measures loudness using EBU R128 standard (ffmpeg)
- Normalizes directly in the audio file — works in every player
- Automatic backup of originals before modifying
- Supports lossless (FLAC, WAV, AIFF, APE, WavPack) and lossy formats (MP3, OGG, OPUS, M4A, AAC, WMA)
- Three loudness targets: Streaming (−14 LUFS), ReplayGain (−18 LUFS), CD/Mastering (−23 LUFS)

## Requirements

- Python 3.12+
- PyQt6
- mutagen
- ffmpeg

```bash
pip install PyQt6 mutagen
```

## Run

```bash
python3 main.py
```

## License

MIT
