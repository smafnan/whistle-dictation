"""Tray controller with explicit capture, inference, cancellation, and focus boundaries."""
from __future__ import annotations

import logging
from dataclasses import replace
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .audio import MicrophoneRecorder
from .config import load_settings, save_settings
from .engine import EngineService
from .session import Session, State
from .ui import Indicator, MainWindow, SettingsDialog, tray_icon
from .win32 import GlobalHotkey, capture_target, insert_text

LOGGER = logging.getLogger("whistle_dictation")


def setup_logging(root: Path) -> None:
    directory = root / "data"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / "app.log", maxBytes=256_000, backupCount=2,
                                 encoding="utf-8")
    # Never log transcripts, samples, dictionary entries or application/window titles.
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


class TrayApplication(QObject):
    shortcut_pressed = Signal()

    def __init__(self, application: QApplication, root: Path, *, hidden: bool = False,
                 engine=None, recorder_factory=MicrophoneRecorder, hotkey_override: str | None = None):
        super().__init__()
        self.application = application
        self.root = root
        self.settings_path = root / "data" / "settings.json"
        self.settings = load_settings(self.settings_path)
        if hotkey_override:
            self.settings = replace(self.settings, hotkey=hotkey_override).validate()
        self.session = Session()
        self.engine = engine if engine is not None else EngineService(root)
        self.recorder_factory = recorder_factory
        self.recorder = None
        self.record_settings = None
        self.overflow = False
        self._closed = False
        self._settings_open = False
        self._hotkey_error = None
        self.window = MainWindow()
        self.window.apply_settings(self.settings)
        self.indicator = Indicator()
        self.tray = QSystemTrayIcon(tray_icon(), self)
        self.tray.setToolTip("Whistle Dictation")
        self.menu = QMenu()
        self.open_action = self.menu.addAction("Open Whistle Dictation")
        self.status_action = self.menu.addAction("Preparing engine…")
        self.status_action.setEnabled(False)
        self.menu.addSeparator()
        self.cancel_action = self.menu.addAction("Cancel dictation")
        self.copy_action = self.menu.addAction("Copy last transcript")
        self.clear_action = self.menu.addAction("Clear transcript")
        self.settings_action = self.menu.addAction("Settings…")
        self.retry_action = self.menu.addAction("Retry engine")
        self.menu.addSeparator()
        quit_action = QAction("Quit", self.menu)
        self.menu.addAction(quit_action)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activate)
        self.open_action.triggered.connect(self.show)
        self.cancel_action.triggered.connect(self.cancel)
        self.copy_action.triggered.connect(self.copy)
        self.clear_action.triggered.connect(self.clear)
        self.settings_action.triggered.connect(self.edit_settings)
        self.retry_action.triggered.connect(self.retry)
        quit_action.triggered.connect(self.quit)
        self.window.preview_button.clicked.connect(lambda: self.toggle(preview=True))
        self.window.cancel_button.clicked.connect(self.cancel)
        self.window.settings_button.clicked.connect(self.edit_settings)
        self.window.retry_button.clicked.connect(self.retry)
        self.window.copy_button.clicked.connect(self.copy)
        self.window.clear_button.clicked.connect(self.clear)
        self.shortcut_pressed.connect(self.toggle)
        self.hotkey = GlobalHotkey(self.settings.hotkey, self.shortcut_pressed.emit)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        try:
            self.hotkey.start()
        except Exception as exc:
            self.hotkey.stop()
            self._hotkey_error = str(exc)
            LOGGER.warning("Hotkey registration failed")
        try:
            self.engine.start()
        except Exception:
            self.hotkey.stop()
            self.engine.close()
            raise
        self.timer.start()
        self.application.aboutToQuit.connect(self.shutdown)
        self.tray.show()
        self.set_status("Preparing local speech engine…")
        if not hidden:
            self.window.show()
        LOGGER.info("Application started")

    def _activate(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()

    def show(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def set_status(self, message: str) -> None:
        if self._hotkey_error:
            message += " Shortcut unavailable — choose another in Settings."
        self.window.status.setText(message)
        self.status_action.setText(message)
        self.tray.setToolTip(f"Whistle Dictation · {message[:100]}")
        active = self.session.state in (State.RECORDING, State.PROCESSING)
        ready = self.session.state == State.READY
        recording = self.session.state == State.RECORDING
        has_text = bool(self.window.transcript.toPlainText())
        self.window.preview_button.setEnabled(ready or recording)
        self.window.preview_button.setText("Stop recording" if recording else "Test microphone")
        self.window.cancel_button.setEnabled(active)
        self.cancel_action.setEnabled(active)
        self.window.settings_button.setEnabled(not active)
        self.settings_action.setEnabled(not active)
        self.window.retry_button.setEnabled(self.session.state == State.ERROR)
        self.retry_action.setEnabled(self.session.state == State.ERROR)
        self.copy_action.setEnabled(has_text)
        self.window.copy_button.setEnabled(has_text)
        self.clear_action.setEnabled(has_text)
        self.window.clear_button.setEnabled(has_text)
        self.tray.setIcon(tray_icon("#ff7979" if recording else "#74dbca"))

    def notice(self, message: str) -> None:
        self.tray.showMessage("Whistle Dictation", message, QSystemTrayIcon.MessageIcon.Information, 4000)

    def close_recorder(self) -> None:
        recorder, self.recorder = self.recorder, None
        if recorder:
            try:
                recorder.close()
            except Exception:
                LOGGER.warning("Microphone close failed")

    def toggle(self, *, preview: bool = False) -> None:
        if self._closed:
            return
        if self._settings_open:
            self.notice("Close Settings before starting dictation.")
            return
        if self.session.state == State.RECORDING:
            self.stop_recording()
            return
        if self.session.state != State.READY:
            self.notice("Speech engine is busy or unavailable. Open the tray app for its status.")
            return
        try:
            target = None if preview else capture_target()
            self.recorder = self.recorder_factory(device=self.settings.microphone,
                                                  max_seconds=self.settings.max_record_seconds)
            self.recorder.start()
            self.record_settings = self.settings
            self.overflow = False
            self.session.start(target)
            self.set_status("Listening — press the shortcut again to stop.")
            self.indicator.display(f"● Listening   ·   {self.settings.hotkey} to stop",
                                   self.application.primaryScreen())
            LOGGER.info("Recording started")
        except Exception as exc:
            self.close_recorder()
            self.session.reset()
            self.set_status(f"Could not start recording: {exc}")
            self.notice("Could not start recording. Check microphone permissions and selected device.")
            LOGGER.warning("Recording start failed (%s)", type(exc).__name__)

    def stop_recording(self) -> None:
        try:
            captured = self.recorder.stop()
            self.recorder = None
            if captured.duration < 0.15:
                self.session.reset()
                self.indicator.hide()
                self.set_status("Recording was too short. Ready to try again.")
                return
            self.overflow = captured.overflow
            self.session.process()
            self.engine.submit(self.session.request_id, captured, self.record_settings)
            self.set_status("Transcribing locally…")
            self.indicator.display("Processing your dictation…", self.application.primaryScreen())
            LOGGER.info("Transcription submitted (%.1f seconds)", captured.duration)
        except Exception as exc:
            self.close_recorder()
            self.indicator.hide()
            self.session.reset()
            self.set_status(f"Recording failed: {exc}")
            self.notice("Recording failed. No text was inserted.")
            LOGGER.warning("Recording stop failed (%s)", type(exc).__name__)

    def tick(self) -> None:
        if self._closed:
            return
        if self.session.state == State.RECORDING and self.recorder:
            self.indicator.label.setText(f"● Listening  {self.recorder.elapsed:.0f}s  ·  {self.settings.hotkey}")
            if self.recorder.limit_reached:
                self.stop_recording()
                self.notice("Recording capacity reached; processing what you recorded.")
        try:
            for message in self.engine.poll():
                self.handle_event(message)
        except Exception as exc:
            self.handle_event({"kind": "error", "request_id": None,
                               "message": f"Speech engine communication failed: {exc}"})

    def handle_event(self, message: dict) -> None:
        kind = message["kind"]
        if kind == "ready":
            self.session.ready()
            self.set_status("Ready — click your textbox and press the shortcut.")
            return
        if kind == "error":
            request_id = message.get("request_id")
            if request_id is not None and not self.session.accepts(request_id):
                return
            self.close_recorder()
            self.indicator.hide()
            self.session.fail()
            self.engine.close()
            self.set_status(message["message"])
            self.notice("Speech engine needs attention. Open the app and use Retry engine.")
            LOGGER.warning("Speech engine error")
            return
        if not self.session.accepts(message.get("request_id")):
            return
        if kind == "progress":
            self.set_status(f"Transcribing segment {message['current']} of {message['total']}…")
            return
        if kind != "result":
            return
        self.indicator.hide()
        text = message["text"]
        target = self.session.target
        self.session.complete(message["request_id"])
        self.window.transcript.setPlainText(text)
        self.window.details.setText(f"{message['seconds']:.2f}s · {message['chunks']} segment(s)")
        if not text:
            self.set_status("No speech detected. Ready.")
        elif self.overflow:
            self.set_status("Microphone lost audio. Review the transcript, then copy it if needed.")
            self.notice("Some microphone audio was lost. Transcript kept for review.")
        elif target is None:
            self.set_status("Microphone test complete. Use the shortcut in another app to dictate.")
        else:
            try:
                suffix = " " if self.record_settings.trailing_space else ""
                insert_text(text + suffix, target)
                self.set_status("Text inserted. Ready for your next dictation.")
                LOGGER.info("Dictation inserted (%d characters)", len(text))
            except Exception as exc:
                self.set_status(f"Text kept for copying: {exc}")
                self.notice("Text was not fully inserted. Open the app to review and copy the transcript.")
                LOGGER.warning("Insertion stopped (%s)", type(exc).__name__)
        self.session.target = None
        self.session.request_id = None

    def cancel(self) -> None:
        processing = self.session.state == State.PROCESSING
        if self.session.state not in (State.RECORDING, State.PROCESSING):
            return
        self.close_recorder()
        self.indicator.hide()
        self.session.reset(reload=processing)
        if processing:
            try:
                self.engine.start()  # Destroy worker; cancelled calls cannot later inject text.
                self.set_status("Cancelled. Reloading speech engine…")
            except Exception as exc:
                self.session.fail()
                self.set_status(f"Cancelled. Could not reload speech engine: {exc}")
        else:
            self.set_status("Cancelled. Ready.")
        LOGGER.info("Dictation cancelled")

    def retry(self) -> None:
        if self.session.state != State.ERROR:
            return
        self.session.reset(reload=True)
        try:
            self.engine.start()
            self.set_status("Reloading local speech engine…")
        except Exception as exc:
            self.session.fail()
            self.set_status(f"Could not restart engine: {exc}")

    def copy(self) -> None:
        text = self.window.transcript.toPlainText()
        if text:
            self.application.clipboard().setText(text)
            self.set_status("Transcript copied to clipboard.")

    def clear(self) -> None:
        self.window.transcript.clear()
        self.window.details.clear()
        self.set_status("Transcript cleared.")

    def edit_settings(self) -> None:
        if self._settings_open or self.session.state in (State.RECORDING, State.PROCESSING):
            return
        self._settings_open = True
        try:
            dialog = SettingsDialog(self.settings, self.window)
            accepted = dialog.exec()
        finally:
            self._settings_open = False
        if not accepted or dialog.result_settings is None:
            return
        new = dialog.result_settings
        old = self.settings
        new_listener = None
        try:
            if new.hotkey != old.hotkey or self._hotkey_error:
                new_listener = GlobalHotkey(new.hotkey, self.shortcut_pressed.emit)
                new_listener.start()  # Keep the old shortcut if registration fails.
            save_settings(self.settings_path, new)
        except Exception as exc:
            if new_listener:
                new_listener.stop()
            QMessageBox.warning(self.window, "Settings not saved", str(exc))
            return
        if new_listener:
            self.hotkey.stop()
            self.hotkey = new_listener
            self._hotkey_error = None
        self.settings = new
        self.window.apply_settings(new)
        self.set_status("Settings saved.")

    def quit(self) -> None:
        self.window.quitting = True
        self.shutdown()
        self.application.quit()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
        self.session.close()
        self.hotkey.stop()
        self.close_recorder()
        self.engine.close()
        self.indicator.close()
        self.tray.hide()
        self.window.quitting = True
        self.window.close()
        LOGGER.info("Application stopped")
