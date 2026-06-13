Name:           ohmega
Version:        1.2.0
Release:        1%{?dist}
Summary:        Normalize audio loudness directly in your files
License:        GPL-3.0-only

URL:            https://github.com/Daniel-v8/Ohmega
Source0:        %{url}/archive/v%{version}/Ohmega-%{version}.tar.gz

BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  desktop-file-utils
BuildRequires:  appstream

Requires:       python3-pyqt6
Requires:       python3-mutagen
# ffmpeg is in RPM Fusion Free — enable it in your COPR project settings
Requires:       ffmpeg

%description
Ohmega normalizes the loudness of your audio files using the EBU R128 standard
(LUFS metering via ffmpeg). Unlike ReplayGain tags, the gain is written directly
into the audio data, so every player plays at the correct volume without any
configuration.

Supports: FLAC, WAV, AIFF, APE, WavPack (lossless), MP3, OGG, OPUS, M4A, AAC, WMA.

%prep
%autosetup -n Ohmega-%{version}

%install
install -Dm644 main.py        %{buildroot}%{_datadir}/ohmega/main.py
install -Dm644 ohmega.png     %{buildroot}%{_datadir}/ohmega/ohmega.png
install -Dm644 ohmega-512.png %{buildroot}%{_datadir}/pixmaps/ohmega.png

install -Dm644 flatpak/io.github.Daniel_v8.Ohmega.desktop \
    %{buildroot}%{_datadir}/applications/ohmega.desktop
install -Dm644 flatpak/io.github.Daniel_v8.Ohmega.metainfo.xml \
    %{buildroot}%{_datadir}/metainfo/io.github.Daniel_v8.Ohmega.metainfo.xml

mkdir -p %{buildroot}%{_bindir}
printf '#!/bin/bash\nexec python3 /usr/share/ohmega/main.py "$@"\n' \
    > %{buildroot}%{_bindir}/ohmega
chmod 755 %{buildroot}%{_bindir}/ohmega

sed -i 's|^Icon=.*|Icon=ohmega|' \
    %{buildroot}%{_datadir}/applications/ohmega.desktop

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/ohmega.desktop
appstreamcli validate --no-net \
    %{buildroot}%{_datadir}/metainfo/io.github.Daniel_v8.Ohmega.metainfo.xml

%files
%doc README.md
%{_bindir}/ohmega
%{_datadir}/ohmega/
%{_datadir}/pixmaps/ohmega.png
%{_datadir}/applications/ohmega.desktop
%{_datadir}/metainfo/io.github.Daniel_v8.Ohmega.metainfo.xml

%changelog
* Sat Jun 13 2026 Daniel-v8 <dany.rcmodelar@proton.me> - 1.2.0-1
- Add album gain: one shared gain per folder (EBU R128), preserving the loudness balance between tracks; handles multiple folders at once

* Tue May 19 2026 Daniel-v8 <dany.rcmodelar@proton.me> - 1.1.2-1
- Rename Flatpak app-id to io.github.Daniel_v8.Ohmega

* Mon May 18 2026 Daniel-v8 <dany.rcmodelar@proton.me> - 1.1.1-1
- Fix backup failing for files opened via drag and drop (Flatpak portal paths)

* Sun May 17 2026 Daniel-v8 <dany.rcmodelar@proton.me> - 1.1.0-1
- Rebranded to Ohmega, new icon, orange accent color

* Fri May 15 2026 Daniel-v8 <dany.rcmodelar@proton.me> - 1.0.0-1
- Initial release
