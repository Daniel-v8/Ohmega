#!/usr/bin/env python3.12
import sys
import os
import json
import subprocess
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QProgressBar, QHeaderView, QAbstractItemView, QComboBox, QCheckBox,
    QDoubleSpinBox, QInputDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QEvent
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QColor, QIcon

from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TXXX

TARGETS = {
    "Streaming (-14 LUFS)": -14.0,
    "ReplayGain 2.0 (-18 LUFS)": -18.0,
    "Broadcast / Film (-23 LUFS)": -23.0,
}

ICON_PATH = str(Path(__file__).parent / "ohmega.png")
PROFILES_PATH = Path.home() / ".config" / "ohmega" / "profiles.json"


def load_profiles() -> dict:
    if PROFILES_PATH.exists():
        try:
            return json.loads(PROFILES_PATH.read_text())
        except Exception:
            pass
    return {}


def save_profiles(profiles: dict):
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_PATH.write_text(json.dumps(profiles, indent=2))


def measure_lufs(filepath: str) -> float:
    result = subprocess.run(
        ["ffmpeg", "-i", filepath, "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True
    )
    for line in reversed(result.stderr.splitlines()):
        if "I:" in line and "LUFS" in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if p == "I:":
                    return float(parts[i + 1])
    raise ValueError(f"Could not measure loudness: {filepath}")


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


class ScanWorker(QThread):
    progress = pyqtSignal(int, str, float)
    done = pyqtSignal()

    def __init__(self, files):
        super().__init__()
        self.files = files

    def run(self):
        for i, f in enumerate(self.files):
            try:
                lufs = measure_lufs(f)
                self.progress.emit(i, "measured", lufs)
            except Exception as e:
                self.progress.emit(i, f"error: {e}", 0.0)
        self.done.emit()


def backup_file(filepath: str) -> str:
    p = Path(filepath)
    # Flatpak document portal paths (/run/user/…) are read-only dirs — back up to ~/Ohmega Backup instead
    if str(p).startswith("/run/user/"):
        backup_dir = Path.home() / "Ohmega Backup"
    else:
        backup_dir = p.parent / "Ohmega Backup"
    backup_dir.mkdir(exist_ok=True)
    dest = backup_dir / p.name
    if not dest.exists():
        import shutil
        shutil.copy2(filepath, dest)
    return str(backup_dir)


class ApplyWorker(QThread):
    progress = pyqtSignal(int, str)
    done = pyqtSignal()

    def __init__(self, files, lufs_values, target, do_backup):
        super().__init__()
        self.files = files
        self.lufs_values = lufs_values
        self.target = target
        self.do_backup = do_backup

    def run(self):
        for i, (f, lufs) in enumerate(zip(self.files, self.lufs_values)):
            if lufs is None:
                continue
            try:
                if self.do_backup:
                    backup_file(f)
                gain = self.target - lufs
                apply_gain_direct(f, gain)
                self.progress.emit(i, f"{gain:+.1f} dB ✓")
            except Exception as e:
                self.progress.emit(i, f"error: {e}")
        self.done.emit()


class DropArea(QWidget):
    files_dropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(80)
        layout = QVBoxLayout(self)
        label = QLabel("Drop audio files or a folder here  •  FLAC · WAV · MP3 · OGG · OPUS · M4A · AAC · WMA · APE · WV")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #888; font-size: 13px;")
        layout.addWidget(label)
        self.setStyleSheet("""
            DropArea {
                border: 2px dashed #555;
                border-radius: 8px;
                background: #1e1e1e;
            }
        """)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e: QDropEvent):
        files = []
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                for root, _, fnames in os.walk(path):
                    for fn in fnames:
                        if fn.lower().endswith(SUPPORTED_EXTENSIONS):
                            files.append(os.path.join(root, fn))
            elif path.lower().endswith(SUPPORTED_EXTENSIONS):
                files.append(path)
        if files:
            self.files_dropped.emit(files)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ohmega")
        self.setMinimumSize(800, 580)
        self.setWindowIcon(QIcon(ICON_PATH))
        self.files = []
        self.lufs_values = []
        self._profiles = load_profiles()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        self.drop_area = DropArea()
        self.drop_area.files_dropped.connect(self.add_files)
        layout.addWidget(self.drop_area)

        # Main controls row
        ctrl = QHBoxLayout()
        self.btn_add = QPushButton("+ Add files")
        self.btn_add.clicked.connect(self.browse_files)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.clear_files)

        self.target_combo = QComboBox()
        for label in TARGETS:
            self.target_combo.addItem(label)
        self.target_combo.addItem("Custom")
        self.target_combo.currentTextChanged.connect(self._on_target_changed)

        self.custom_lufs_spin = QDoubleSpinBox()
        self.custom_lufs_spin.setRange(-50.0, 0.0)
        self.custom_lufs_spin.setValue(-16.0)
        self.custom_lufs_spin.setSuffix(" LUFS")
        self.custom_lufs_spin.setDecimals(1)
        self.custom_lufs_spin.setFixedWidth(105)
        self.custom_lufs_spin.setVisible(False)

        self.btn_scan = QPushButton("Scan loudness")
        self.btn_scan.clicked.connect(self.scan)
        self.btn_apply = QPushButton("Normalize loudness")
        self.btn_apply.clicked.connect(self.apply)
        self.btn_apply.setEnabled(False)
        self.btn_apply.setStyleSheet("QPushButton { background: #c94b0a; color: white; } QPushButton:hover { background: #e05510; color: white; }")

        self.chk_backup = QCheckBox("Backup originals")
        self.chk_backup.setChecked(True)
        self.chk_backup.setToolTip("Copies originals to 'Ohmega Backup/' subfolder before modifying")

        for w in [self.btn_add, self.btn_clear, self.target_combo, self.custom_lufs_spin,
                  self.btn_scan, self.chk_backup, self.btn_apply]:
            ctrl.addWidget(w)
        layout.addLayout(ctrl)

        # Profiles row
        prof = QHBoxLayout()
        prof.addWidget(QLabel("Profile:"))

        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(160)
        self.profile_combo.addItem("(no profile)")
        for name in self._profiles:
            self.profile_combo.addItem(name)
        self.profile_combo.currentTextChanged.connect(self._on_profile_selected)
        prof.addWidget(self.profile_combo)

        self.btn_profile_save = QPushButton("Save")
        self.btn_profile_save.setToolTip("Save current settings as a profile")
        self.btn_profile_save.clicked.connect(self._save_profile)
        prof.addWidget(self.btn_profile_save)

        self.btn_profile_delete = QPushButton("Delete")
        self.btn_profile_delete.setToolTip("Delete selected profile")
        self.btn_profile_delete.setEnabled(False)
        self.btn_profile_delete.clicked.connect(self._delete_profile)
        prof.addWidget(self.btn_profile_delete)

        prof.addStretch()
        layout.addLayout(prof)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "Format", "Loudness (LUFS)", "Gain"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.installEventFilter(self)
        layout.addWidget(self.table)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status = QLabel("Add files and click Scan  •  Select a row and press Delete to remove it")
        self.status.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(self.status)

    def eventFilter(self, obj, event):
        if obj is self.table and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Delete:
                self._delete_selected_rows()
                return True
        return super().eventFilter(obj, event)

    def current_target(self) -> float:
        label = self.target_combo.currentText()
        if label == "Custom":
            return self.custom_lufs_spin.value()
        return TARGETS[label]

    def _on_target_changed(self, text):
        self.custom_lufs_spin.setVisible(text == "Custom")

    def add_files(self, files):
        existing = set(self.files)
        new = [f for f in files if f not in existing]
        for f in new:
            self.files.append(f)
            self.lufs_values.append(None)
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(Path(f).name))
            ext = Path(f).suffix.lower()
            fmt_label = Path(f).suffix.upper().lstrip(".")
            fmt_item = QTableWidgetItem(fmt_label)
            if ext not in LOSSLESS_EXTENSIONS:
                fmt_item.setForeground(QColor("#ff9800"))
                fmt_item.setToolTip("Lossy format — small quality loss on re-encode")
            self.table.setItem(row, 1, fmt_item)
            self.table.setItem(row, 2, QTableWidgetItem("—"))
            self.table.setItem(row, 3, QTableWidgetItem("—"))
        self.btn_apply.setEnabled(False)
        self.status.setText(f"{len(self.files)} file(s) loaded")

    def browse_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select files", str(Path.home()),
            "Audio files (*.flac *.mp3 *.wav *.aiff *.aif *.ogg *.opus *.m4a *.aac *.wma *.ape *.wv *.mpc)"
        )
        if paths:
            self.add_files(paths)

    def clear_files(self):
        self.files.clear()
        self.lufs_values.clear()
        self.table.setRowCount(0)
        self.btn_apply.setEnabled(False)
        self.status.setText("Add files and click Scan")

    def _delete_selected_rows(self):
        rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()), reverse=True)
        for row in rows:
            self.table.removeRow(row)
            del self.files[row]
            del self.lufs_values[row]
        if not self.files:
            self.btn_apply.setEnabled(False)
            self.status.setText("Add files and click Scan")
        else:
            self.status.setText(f"{len(self.files)} file(s) loaded")

    def scan(self):
        if not self.files:
            return
        self.btn_scan.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setMaximum(len(self.files))
        self.progress.setValue(0)
        self.lufs_values = [None] * len(self.files)

        self.worker = ScanWorker(self.files)
        self.worker.progress.connect(self._on_scan_progress)
        self.worker.done.connect(self._on_scan_done)
        self.worker.start()

    def _on_scan_progress(self, row, status, lufs):
        self.progress.setValue(row + 1)
        self.status.setText(f"Scanning {row + 1}/{len(self.files)}: {Path(self.files[row]).name}")
        if status == "measured":
            self.lufs_values[row] = lufs
            item = QTableWidgetItem(f"{lufs:.1f} LUFS")
            target = self.current_target()
            diff = lufs - target
            if abs(diff) < 1:
                item.setForeground(QColor("#4caf50"))
            elif diff > 6:
                item.setForeground(QColor("#f44336"))
            else:
                item.setForeground(QColor("#ff9800"))
            self.table.setItem(row, 2, item)
        else:
            self.table.setItem(row, 2, QTableWidgetItem(status))

    def _on_scan_done(self):
        self.btn_scan.setEnabled(True)
        self.progress.setVisible(False)
        measured = sum(1 for v in self.lufs_values if v is not None)
        self.status.setText(f"Done — {measured}/{len(self.files)} files scanned")
        if measured > 0:
            self.btn_apply.setEnabled(True)

    def apply(self):
        target = self.current_target()
        self.btn_apply.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setMaximum(len(self.files))
        self.progress.setValue(0)

        self.apply_worker = ApplyWorker(self.files, self.lufs_values, target, self.chk_backup.isChecked())
        self.apply_worker.progress.connect(self._on_apply_progress)
        self.apply_worker.done.connect(self._on_apply_done)
        self.apply_worker.start()

    def _on_apply_progress(self, row, result):
        self.progress.setValue(row + 1)
        self.status.setText(f"Processing {row + 1}/{len(self.files)}: {Path(self.files[row]).name}")
        item = QTableWidgetItem(result)
        if "error" not in result:
            item.setForeground(QColor("#4caf50"))
        else:
            item.setForeground(QColor("#f44336"))
        self.table.setItem(row, 3, item)

    def _on_apply_done(self):
        self.btn_scan.setEnabled(True)
        self.btn_apply.setEnabled(True)
        self.progress.setVisible(False)
        backed = " + backup created" if self.apply_worker.do_backup else ""
        self.status.setText(f"Done — loudness normalized directly in files{backed} — Ω")
        try:
            subprocess.Popen(
                ["notify-send", "-a", "Ohmega", "-i", ICON_PATH,
                 "Ohmega", f"{len(self.files)} file(s) normalized{backed}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            pass

    # ── Profiles ─────────────────────────────────────────────────────────────

    def _on_profile_selected(self, name):
        self.btn_profile_delete.setEnabled(name != "(no profile)")
        if name == "(no profile)" or name not in self._profiles:
            return
        p = self._profiles[name]
        label = p.get("target_label", "Streaming (-14 LUFS)")
        if label in TARGETS:
            self.target_combo.setCurrentText(label)
        elif label == "Custom":
            self.target_combo.setCurrentText("Custom")
            self.custom_lufs_spin.setValue(p.get("custom_lufs", -16.0))
        self.chk_backup.setChecked(p.get("backup", True))

    def _save_profile(self):
        current_name = self.profile_combo.currentText()
        if current_name == "(no profile)":
            name, ok = QInputDialog.getText(self, "Save Profile", "Profile name:")
            if not ok or not name.strip():
                return
            name = name.strip()
        else:
            name = current_name

        label = self.target_combo.currentText()
        self._profiles[name] = {
            "target_label": label,
            "custom_lufs": self.custom_lufs_spin.value(),
            "backup": self.chk_backup.isChecked(),
        }
        save_profiles(self._profiles)
        self._refresh_profile_combo(select=name)

    def _delete_profile(self):
        name = self.profile_combo.currentText()
        if name == "(no profile)" or name not in self._profiles:
            return
        del self._profiles[name]
        save_profiles(self._profiles)
        self._refresh_profile_combo(select="(no profile)")

    def _refresh_profile_combo(self, select: str = None):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("(no profile)")
        for name in self._profiles:
            self.profile_combo.addItem(name)
        if select:
            idx = self.profile_combo.findText(select)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)
        self.btn_profile_delete.setEnabled(
            self.profile_combo.currentText() != "(no profile)"
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Ohmega")
    app.setDesktopFileName("io.github.Daniel_v8.Ohmega")
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
