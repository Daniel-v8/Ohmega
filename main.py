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
    QDoubleSpinBox, QInputDialog, QListView, QTreeView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QEvent
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QColor, QIcon

from ohmega_core import (
    TARGETS, SUPPORTED_EXTENSIONS, LOSSLESS_EXTENSIONS,
    measure_lufs, measure_album_lufs, apply_gain_direct, backup_file,
    collect_audio_files,
)

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


class ApplyWorker(QThread):
    progress = pyqtSignal(int, str)
    status = pyqtSignal(str)
    done = pyqtSignal()

    def __init__(self, files, lufs_values, album_keys, target, do_backup):
        super().__init__()
        self.files = files
        self.lufs_values = lufs_values
        self.album_keys = album_keys
        self.target = target
        self.do_backup = do_backup

    def run(self):
        # Files added as part of a folder share an album key and get one shared
        # gain (loudness balance between tracks preserved); loose files added
        # individually (album key None) are normalized per track.
        groups = {}
        for i, key in enumerate(self.album_keys):
            if key is not None:
                groups.setdefault(key, []).append(i)
        grouped = set()
        for idxs in groups.values():
            grouped.update(idxs)

        for folder, idxs in groups.items():
            try:
                self.status.emit(f"Measuring album: {Path(folder).name}")
                album_lufs = measure_album_lufs([self.files[i] for i in idxs])
            except Exception as e:
                for i in idxs:
                    self.progress.emit(i, f"error: {e}")
                continue
            gain = self.target - album_lufs
            if abs(gain) < 0.5:
                for i in idxs:
                    self.progress.emit(i, "skipped ✓ (album)")
                continue
            for i in idxs:
                self._apply_one(i, gain, suffix=" (album)")

        for i, lufs in enumerate(self.lufs_values):
            if i in grouped or lufs is None:
                continue
            gain = self.target - lufs
            if abs(gain) < 0.5:
                self.progress.emit(i, "skipped ✓")
                continue
            self._apply_one(i, gain)

        self.done.emit()

    def _apply_one(self, i, gain, suffix=""):
        try:
            if self.do_backup:
                backup_file(self.files[i])
            apply_gain_direct(self.files[i], gain)
            self.progress.emit(i, f"{gain:+.1f} dB ✓{suffix}")
        except Exception as e:
            self.progress.emit(i, f"error: {e}")


class DropArea(QWidget):
    entries_dropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(80)
        layout = QVBoxLayout(self)
        label = QLabel("Drop files or folders here — a folder is one album  •  FLAC · WAV · MP3 · OGG · OPUS · M4A · AAC · WMA · APE · WV")
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
        # Each entry is (path, album_key): a dropped folder becomes one album
        # per parent directory; loose files stay per-track (album_key None).
        entries = []
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                for f in collect_audio_files(path):
                    entries.append((f, str(Path(f).parent)))
            elif path.lower().endswith(SUPPORTED_EXTENSIONS):
                entries.append((path, None))
        if entries:
            self.entries_dropped.emit(entries)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ohmega")
        self.setMinimumSize(800, 580)
        self.setWindowIcon(QIcon(ICON_PATH))
        self.files = []
        self.lufs_values = []
        self.album_keys = []
        self._profiles = load_profiles()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        self.drop_area = DropArea()
        self.drop_area.entries_dropped.connect(self.add_entries)
        layout.addWidget(self.drop_area)

        # Main controls row
        ctrl = QHBoxLayout()
        self.btn_add = QPushButton("+ Add files")
        self.btn_add.clicked.connect(self.browse_files)
        self.btn_add_folder = QPushButton("+ Add folder")
        self.btn_add_folder.setToolTip(
            "Pick one or more folders in the file browser.\n"
            "Each folder is normalized as one album — a single shared gain\n"
            "(EBU R128) that keeps the loudness balance between its tracks."
        )
        self.btn_add_folder.clicked.connect(self.browse_folders)
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

        for w in [self.btn_add, self.btn_add_folder, self.btn_clear, self.target_combo,
                  self.custom_lufs_spin, self.btn_scan, self.chk_backup,
                  self.btn_apply]:
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

    def add_entries(self, entries):
        """entries: list of (path, album_key). album_key is the folder a file
        belongs to (it gets album gain), or None for a loose per-track file."""
        existing = set(self.files)
        for f, album_key in entries:
            if f in existing:
                continue
            existing.add(f)
            self.files.append(f)
            self.lufs_values.append(None)
            self.album_keys.append(album_key)
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(Path(f).name)
            if album_key:
                name_item.setToolTip(f"Album: {Path(album_key).name}")
            self.table.setItem(row, 0, name_item)
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
        albums = len({k for k in self.album_keys if k})
        if albums:
            self.status.setText(f"{len(self.files)} file(s) loaded — {albums} album(s)")
        else:
            self.status.setText(f"{len(self.files)} file(s) loaded")

    def browse_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select files", str(Path.home()),
            "Audio files (*.flac *.mp3 *.wav *.aiff *.aif *.ogg *.opus *.m4a *.aac *.wma *.ape *.wv *.mpc)"
        )
        if paths:
            self.add_entries([(p, None) for p in paths])

    def browse_folders(self):
        # Qt's native directory picker allows only one folder, so use the
        # non-native dialog and switch its inner views to multi-selection —
        # lets several albums be added in one go.
        dialog = QFileDialog(self, "Select folder(s)")
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        dialog.setDirectory(str(Path.home()))
        list_view = dialog.findChild(QListView, "listView")
        if list_view:
            list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tree_view = dialog.findChild(QTreeView)
        if tree_view:
            tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        if not dialog.exec():
            return
        entries = []
        for folder in dialog.selectedFiles():
            if not os.path.isdir(folder):
                continue
            # Group by each file's parent dir, so a selected parent that holds
            # several album subfolders yields one album per subfolder.
            for f in collect_audio_files(folder):
                entries.append((f, str(Path(f).parent)))
        if entries:
            self.add_entries(entries)
        else:
            self.status.setText("No supported audio files in the selected folder(s)")

    def clear_files(self):
        self.files.clear()
        self.lufs_values.clear()
        self.album_keys.clear()
        self.table.setRowCount(0)
        self.btn_apply.setEnabled(False)
        self.status.setText("Add files and click Scan")

    def _delete_selected_rows(self):
        rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()), reverse=True)
        for row in rows:
            self.table.removeRow(row)
            del self.files[row]
            del self.lufs_values[row]
            del self.album_keys[row]
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
        self._apply_done_count = 0

        self.apply_worker = ApplyWorker(
            self.files, self.lufs_values, self.album_keys, target,
            self.chk_backup.isChecked()
        )
        self.apply_worker.progress.connect(self._on_apply_progress)
        self.apply_worker.status.connect(self.status.setText)
        self.apply_worker.done.connect(self._on_apply_done)
        self.apply_worker.start()

    def _on_apply_progress(self, row, result):
        self._apply_done_count += 1
        self.progress.setValue(self._apply_done_count)
        self.status.setText(f"Processing {self._apply_done_count}/{len(self.files)}: {Path(self.files[row]).name}")
        item = QTableWidgetItem(result)
        if result.startswith("skipped"):
            item.setForeground(QColor("#888888"))
        elif "error" not in result:
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
