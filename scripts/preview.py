"""Render documentation screenshots without opening a device or registering a shortcut."""
import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase

from whistle_dictation.config import Settings
from whistle_dictation.ui import STYLE, MainWindow


def main():
    application = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf"):
        QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / name))
    application.setStyleSheet(STYLE)
    window = MainWindow()
    window.apply_settings(Settings())
    window.status.setText("Ready — click your textbox and press the shortcut.")
    window.cancel_button.setEnabled(False)
    window.retry_button.setEnabled(False)
    window.transcript.setPlainText("This is a test of local voice dictation. Please schedule a meeting for tomorrow morning.")
    window.details.setText("Example transcript")
    window.show()
    application.processEvents()
    output = Path(__file__).resolve().parents[1] / "docs" / "app-preview.png"
    window.grab().save(str(output))
    window.quitting = True
    window.close()
    print(output)


if __name__ == "__main__":
    main()
