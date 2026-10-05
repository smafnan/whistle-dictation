"""Qt widgets; microphone and inference coordination lives in app.py."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from .audio import input_devices
from .config import Settings

STYLE = """
QWidget { background: #111820; color: #edf3f8; font-family: 'Segoe UI'; font-size: 14px; }
QMainWindow, QDialog { background: #111820; }
QLabel#eyebrow { color: #74dbca; font-size: 12px; font-weight: 700; }
QLabel#title { font-size: 32px; font-weight: 700; }
QLabel#muted { color: #9aafc1; }
QFrame#card { background: #1b2531; border: 1px solid #2a3949; border-radius: 12px; }
QFrame#card QLabel { background: transparent; }
QPushButton { background: #263746; border: 1px solid #3d5368; border-radius: 7px; padding: 10px 16px; }
QPushButton:hover { background: #334b5e; }
QPushButton:disabled { color: #697b8c; background: #1d2933; border-color: #293b49; }
QPushButton#primary { background: #74dbca; color: #112522; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #91e9db; }
QPlainTextEdit, QLineEdit, QComboBox, QSpinBox { background: #18232e; border: 1px solid #3d5368;
 border-radius: 6px; padding: 8px; selection-background-color: #3b786e; }
QPlainTextEdit { padding: 12px; }
QCheckBox { spacing: 8px; }
QMenu { background: #1b2531; border: 1px solid #3d5368; }
QMenu::item { padding: 8px 20px; }
QMenu::item:selected { background: #334b5e; }
"""


def tray_icon(color: str = "#74dbca") -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#16232e"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 16, 16)
    painter.setBrush(QColor(color))
    for i, height in enumerate((14, 26, 38, 26, 14)):
        painter.drawRoundedRect(13 + i * 8, (64 - height) // 2, 5, height, 2, 2)
    painter.end()
    return QIcon(pixmap)


class Indicator(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(390, 54)
        self.setStyleSheet("background: #1b2531; border: 1px solid #74dbca; border-radius: 12px;")
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("border: none; color: #edf3f8; background: transparent;")
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)

    def display(self, text: str, screen) -> None:
        self.label.setText(text)
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.bottom() - self.height() - 28)
        self.show()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Whistle Dictation")
        self.setWindowIcon(tray_icon())
        self.resize(800, 670)
        self.setMinimumSize(650, 530)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)
        eyebrow = QLabel("LOCAL VOICE · WINDOWS")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)
        title = QLabel("Speak into any textbox.")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("Click your textbox, press the shortcut, speak, then press it again.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 15, 18, 15)
        self.status = QLabel("Preparing speech engine…")
        self.status.setWordWrap(True)
        self.shortcut = QLabel()
        self.shortcut.setObjectName("muted")
        self.shortcut.setWordWrap(True)
        card_layout.addWidget(self.status)
        card_layout.addWidget(self.shortcut)
        layout.addWidget(card)
        actions = QHBoxLayout()
        self.preview_button = QPushButton("Test microphone")
        self.preview_button.setObjectName("primary")
        self.cancel_button = QPushButton("Cancel")
        self.settings_button = QPushButton("Settings")
        self.retry_button = QPushButton("Retry engine")
        for button in (self.preview_button, self.cancel_button, self.settings_button, self.retry_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        label = QLabel("LAST TRANSCRIPT")
        label.setObjectName("eyebrow")
        layout.addWidget(label)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText("Your latest dictation appears here. Nothing is saved to disk.")
        layout.addWidget(self.transcript, 1)
        footer = QHBoxLayout()
        self.copy_button = QPushButton("Copy transcript")
        self.clear_button = QPushButton("Clear")
        footer.addWidget(self.copy_button)
        footer.addWidget(self.clear_button)
        footer.addStretch()
        self.details = QLabel("")
        self.details.setObjectName("muted")
        footer.addWidget(self.details)
        layout.addLayout(footer)
        note = QLabel("Closing this window keeps dictation in the tray. Use the tray menu to quit.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.setCentralWidget(container)
        self.quitting = False

    def closeEvent(self, event) -> None:
        if self.quitting:
            event.accept()
        else:
            self.hide()
            event.ignore()

    def apply_settings(self, settings: Settings) -> None:
        language = settings.language.upper() if settings.language else "Auto"
        limit = (f"{settings.max_record_seconds // 60} min" if settings.max_record_seconds % 60 == 0
                 else f"{settings.max_record_seconds}s")
        self.shortcut.setText(f"{settings.hotkey}   ·   {language}   ·   {limit} limit")


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.result_settings = None
        self.setWindowTitle("Dictation settings")
        self.resize(620, 660)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.hotkey = QLineEdit(settings.hotkey)
        form.addRow("Global shortcut", self.hotkey)
        self.language = QComboBox()
        for label, code in (("English", "en"), ("German", "de"), ("French", "fr"),
                            ("Spanish", "es"), ("Italian", "it"), ("Dutch", "nl"),
                            ("Polish", "pl"), ("Detect automatically", None)):
            self.language.addItem(label, code)
        self.language.setCurrentIndex(self.language.findData(settings.language))
        form.addRow("Spoken language", self.language)
        self.microphone = QComboBox()
        self.microphone.addItem("Windows default microphone", None)
        try:
            for device in input_devices():
                self.microphone.addItem(f"{device['index']}: {device['name']}", device["index"])
        except Exception:
            self.microphone.addItem("Device enumeration unavailable", -1)
        selected = self.microphone.findData(settings.microphone)
        if selected < 0 and settings.microphone is not None:
            self.microphone.addItem(f"Unavailable device {settings.microphone}", settings.microphone)
            selected = self.microphone.count() - 1
        self.microphone.setCurrentIndex(max(0, selected))
        form.addRow("Microphone", self.microphone)
        self.maximum = QSpinBox()
        self.maximum.setRange(10, 900)
        self.maximum.setSuffix(" seconds")
        self.maximum.setValue(settings.max_record_seconds)
        form.addRow("Recording limit", self.maximum)
        layout.addLayout(form)
        self.cleanup = QCheckBox("Capitalize the first character and tidy punctuation spacing")
        self.cleanup.setChecked(settings.cleanup)
        self.punctuation = QCheckBox("Add a final period when punctuation is missing")
        self.punctuation.setChecked(settings.terminal_punctuation)
        self.space = QCheckBox("Add a space after inserted text")
        self.space.setChecked(settings.trailing_space)
        for box in (self.cleanup, self.punctuation, self.space):
            layout.addWidget(box)
        layout.addWidget(QLabel("Personal dictionary — one word or phrase per line"))
        self.keywords = QPlainTextEdit("\n".join(settings.keywords))
        self.keywords.setPlaceholderText("Cactus\nWhistle\nYour product name")
        self.keywords.setMaximumHeight(110)
        layout.addWidget(self.keywords)
        layout.addWidget(QLabel("Exact word/phrase replacements — one source => replacement per line"))
        self.replacements = QPlainTextEdit("\n".join(f"{a} => {b}" for a, b in settings.replacements.items()))
        self.replacements.setPlaceholderText("meet ily => Meetily")
        self.replacements.setMaximumHeight(100)
        layout.addWidget(self.replacements)
        note = QLabel("Settings stay on this computer. Changes apply to the next recording.")
        note.setObjectName("muted")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self) -> None:
        try:
            replacements = {}
            for line in self.replacements.toPlainText().splitlines():
                if not line.strip():
                    continue
                if "=>" not in line:
                    raise ValueError("Each replacement needs source => replacement.")
                source, target = (piece.strip() for piece in line.split("=>", 1))
                if source.casefold() in {key.casefold() for key in replacements}:
                    raise ValueError(f"Duplicate replacement: {source}")
                replacements[source] = target
            from .win32 import parse_hotkey
            settings = replace(self.settings, hotkey=parse_hotkey(self.hotkey.text()).canonical,
                language=self.language.currentData(), microphone=self.microphone.currentData(),
                max_record_seconds=self.maximum.value(), cleanup=self.cleanup.isChecked(),
                terminal_punctuation=self.punctuation.isChecked(), trailing_space=self.space.isChecked(),
                keywords=list(dict.fromkeys(line.strip() for line in self.keywords.toPlainText().splitlines() if line.strip())),
                replacements=replacements).validate()
            self.result_settings = settings
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Check settings", str(exc))
