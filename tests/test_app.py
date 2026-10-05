"""Offscreen controller regressions; never open a microphone or inject keystrokes."""

from __future__ import annotations

import os
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from whistle_dictation import app as app_module  # noqa: E402
from whistle_dictation.audio import CapturedAudio  # noqa: E402
from whistle_dictation.session import State  # noqa: E402
from whistle_dictation.win32 import FocusTarget, NativeError  # noqa: E402


class FakeHotkey:
    def __init__(self, spec, on_trigger):
        self.spec = spec
        self.on_trigger = on_trigger
        self.started = False
        self.start_calls = 0
        self.stop_calls = 0
        self.start_error = None

    def start(self):
        self.start_calls += 1
        if self.start_error:
            raise self.start_error
        self.started = True

    def stop(self):
        self.stop_calls += 1
        self.started = False


class FakeEngine:
    def __init__(self):
        self.start_calls = 0
        self.close_calls = 0
        self.start_error = None
        self.submissions = []
        self.events = []
        self.poll_error = None

    def start(self):
        self.start_calls += 1
        if self.start_error:
            raise self.start_error

    def close(self):
        self.close_calls += 1

    def submit(self, request_id, captured, settings):
        self.submissions.append((request_id, captured, settings))

    def poll(self):
        if self.poll_error:
            raise self.poll_error
        events, self.events = self.events, []
        return events


class FakeRecorder:
    def __init__(self, device=None, max_seconds=300):
        self.device = device
        self.max_seconds = max_seconds
        self.held = False
        self.start_calls = 0
        self.stop_calls = 0
        self.close_calls = 0
        self.start_error = None
        self.stop_error = None
        self.close_error = None
        self.elapsed = 1.0
        self.limit_reached = False
        self.captured = CapturedAudio(np.zeros(16000, dtype=np.float32), 16000)

    def start(self):
        self.start_calls += 1
        self.held = True
        if self.start_error:
            raise self.start_error

    def stop(self):
        self.stop_calls += 1
        if self.stop_error:
            raise self.stop_error
        self.held = False
        return self.captured

    def close(self):
        self.close_calls += 1
        self.held = False
        if self.close_error:
            raise self.close_error


@pytest.fixture(scope="session")
def qt_application():
    application = QApplication.instance() or QApplication(["whistle-controller-tests"])
    application.setQuitOnLastWindowClosed(False)
    return application


@pytest.fixture
def harness(monkeypatch, tmp_path, qt_application):
    hotkeys = []
    recorders = []
    controllers = []
    engine = FakeEngine()
    hotkey_state = SimpleNamespace(error=None)
    target = FocusTarget(100, 101, 42)
    capture = Mock(return_value=target)
    insertion = Mock()

    def make_hotkey(spec, callback):
        hotkey = FakeHotkey(spec, callback)
        hotkey.start_error = hotkey_state.error
        hotkeys.append(hotkey)
        return hotkey

    def make_recorder(**kwargs):
        recorder = FakeRecorder(**kwargs)
        recorders.append(recorder)
        return recorder

    monkeypatch.setattr(app_module, "GlobalHotkey", make_hotkey)
    monkeypatch.setattr(app_module, "capture_target", capture)
    monkeypatch.setattr(app_module, "insert_text", insertion)

    def build(*, ready=True, hotkey_override=None):
        controller = app_module.TrayApplication(
            qt_application, tmp_path, hidden=True, engine=engine, recorder_factory=make_recorder,
            hotkey_override=hotkey_override,
        )
        controllers.append(controller)
        controller.timer.stop()
        controller.notice = Mock()
        if ready:
            engine.events.append({"kind": "ready"})
            controller.tick()
        return controller

    yield SimpleNamespace(
        build=build, engine=engine, hotkeys=hotkeys, recorders=recorders,
        target=target, capture=capture, insertion=insertion, qt=qt_application,
        monkeypatch=monkeypatch, hotkey_state=hotkey_state,
    )

    for controller in controllers:
        controller.shutdown()
        controller.window.deleteLater()
        controller.indicator.deleteLater()
        controller.menu.deleteLater()
        controller.deleteLater()
    qt_application.processEvents()


def begin_processing(controller, *, preview=False):
    controller.toggle(preview=preview)
    assert controller.session.state == State.RECORDING
    request_id = controller.session.request_id
    controller.toggle()
    assert controller.session.state == State.PROCESSING
    return request_id


def result(request_id, text="Hello world."):
    return {"kind": "result", "request_id": request_id, "text": text, "seconds": 0.25, "chunks": 1}


def test_preview_displays_transcript_without_capturing_target_or_inserting(harness):
    controller = harness.build()
    request_id = begin_processing(controller, preview=True)
    harness.engine.events.append(result(request_id))
    controller.tick()

    harness.capture.assert_not_called()
    harness.insertion.assert_not_called()
    assert controller.window.transcript.toPlainText() == "Hello world."
    assert "Microphone test complete" in controller.window.status.text()
    assert controller.session.state == State.READY
    assert not harness.recorders[0].held


def test_dictation_uses_original_target_and_inserts_exactly_once(harness):
    controller = harness.build()
    request_id = begin_processing(controller)
    original_settings = controller.record_settings
    completed = result(request_id)
    controller.handle_event(completed)
    controller.handle_event(completed)

    harness.capture.assert_called_once_with()
    harness.insertion.assert_called_once_with("Hello world. ", harness.target)
    assert harness.engine.submissions[0][0] == request_id
    assert harness.engine.submissions[0][2] is original_settings
    assert controller.session.state == State.READY
    assert controller.session.target is None
    assert controller.session.request_id is None


def test_settings_snapshot_controls_trailing_space(harness):
    controller = harness.build()
    controller.settings = replace(controller.settings, trailing_space=False)
    request_id = begin_processing(controller)
    controller.settings = replace(controller.settings, trailing_space=True)
    controller.handle_event(result(request_id))

    harness.insertion.assert_called_once_with("Hello world.", harness.target)


def test_cancelled_request_cannot_insert_even_after_engine_becomes_ready(harness):
    controller = harness.build()
    request_id = begin_processing(controller)
    controller.cancel()
    assert controller.session.state == State.LOADING
    assert harness.engine.start_calls == 2
    controller.handle_event(result(request_id, "Cancelled secret"))
    controller.handle_event({"kind": "ready"})
    controller.handle_event(result(request_id, "Cancelled secret"))

    harness.insertion.assert_not_called()
    assert controller.window.transcript.toPlainText() == ""
    assert controller.session.state == State.READY


def test_stale_result_does_not_overwrite_new_recording(harness):
    controller = harness.build()
    old_id = begin_processing(controller)
    controller.cancel()
    controller.handle_event({"kind": "ready"})
    new_id = begin_processing(controller)
    controller.handle_event(result(old_id, "Old request"))
    assert controller.session.state == State.PROCESSING
    assert controller.session.request_id == new_id
    assert controller.window.transcript.toPlainText() == ""
    controller.handle_event(result(new_id, "New request"))

    harness.insertion.assert_called_once_with("New request ", harness.target)


@pytest.mark.parametrize("failure", ["focused field changed", "Windows blocked input"])
def test_insertion_failure_keeps_transcript_for_copying(harness, failure):
    controller = harness.build()
    request_id = begin_processing(controller)
    harness.insertion.side_effect = NativeError(failure)
    controller.handle_event(result(request_id))

    assert controller.window.transcript.toPlainText() == "Hello world."
    assert "Text kept for copying" in controller.window.status.text()
    assert failure in controller.window.status.text()
    assert controller.window.copy_button.isEnabled()
    assert controller.session.state == State.READY
    controller.handle_event(result(request_id))
    assert harness.insertion.call_count == 1


def test_microphone_overflow_prevents_auto_insertion(harness):
    controller = harness.build()
    controller.toggle()
    harness.recorders[0].captured = replace(harness.recorders[0].captured, overflow=True)
    request_id = controller.session.request_id
    controller.toggle()
    controller.handle_event(result(request_id))

    harness.insertion.assert_not_called()
    assert controller.window.transcript.toPlainText() == "Hello world."
    assert "lost audio" in controller.window.status.text()
    assert controller.session.state == State.READY


def test_empty_result_does_not_insert_or_add_space(harness):
    controller = harness.build()
    request_id = begin_processing(controller)
    controller.handle_event(result(request_id, ""))

    harness.insertion.assert_not_called()
    assert "No speech detected" in controller.window.status.text()
    assert not controller.window.copy_button.isEnabled()


def test_worker_error_requires_retry_and_ignores_old_result(harness):
    controller = harness.build()
    request_id = begin_processing(controller)
    controller.handle_event({"kind": "error", "request_id": request_id, "message": "Engine unavailable"})
    assert controller.session.state == State.ERROR
    assert harness.engine.close_calls == 1
    assert controller.window.retry_button.isEnabled()
    controller.handle_event(result(request_id))
    harness.insertion.assert_not_called()
    controller.retry()
    assert controller.session.state == State.LOADING
    assert harness.engine.start_calls == 2
    controller.handle_event({"kind": "ready"})
    assert controller.session.state == State.READY


def test_retry_failure_returns_to_error(harness):
    controller = harness.build()
    controller.handle_event({"kind": "error", "request_id": None, "message": "Worker failed"})
    harness.engine.start_error = RuntimeError("Restart failed")
    controller.retry()

    assert controller.session.state == State.ERROR
    assert "Restart failed" in controller.window.status.text()
    assert controller.window.retry_button.isEnabled()


def test_settings_disabled_and_dialog_guarded_during_active_session(harness):
    controller = harness.build()
    settings_dialog = Mock()
    harness.monkeypatch.setattr(app_module, "SettingsDialog", settings_dialog)
    controller.toggle()
    assert not controller.settings_action.isEnabled()
    assert not controller.window.settings_button.isEnabled()
    controller.edit_settings()
    controller.toggle()
    assert not controller.settings_action.isEnabled()
    assert not controller.window.settings_button.isEnabled()
    controller.edit_settings()

    settings_dialog.assert_not_called()


def test_clear_transcript_preserves_active_request_and_control_state(harness):
    controller = harness.build()
    controller.window.transcript.setPlainText("Previous transcript")
    request_id = begin_processing(controller)
    controller.clear()

    assert controller.window.transcript.toPlainText() == ""
    assert controller.session.state == State.PROCESSING
    assert controller.session.request_id == request_id
    assert controller.session.target is harness.target
    assert not controller.window.settings_button.isEnabled()
    assert not controller.window.preview_button.isEnabled()
    assert controller.window.cancel_button.isEnabled()


def test_capture_failure_never_opens_microphone(harness):
    controller = harness.build()
    harness.capture.side_effect = NativeError("No focused field")
    controller.toggle()

    assert not harness.recorders
    assert controller.session.state == State.READY
    assert "No focused field" in controller.window.status.text()
    harness.insertion.assert_not_called()


def test_stop_failure_closes_microphone_and_restores_ready(harness):
    controller = harness.build()
    controller.toggle()
    recorder = harness.recorders[0]
    recorder.stop_error = RuntimeError("Device disappeared")
    controller.toggle()

    assert not recorder.held
    assert recorder.close_calls == 1
    assert controller.recorder is None
    assert controller.session.state == State.READY
    assert not harness.engine.submissions


def test_short_recording_discards_audio_without_engine_submission(harness):
    controller = harness.build()
    controller.toggle()
    harness.recorders[0].captured = CapturedAudio(np.zeros(100, dtype=np.float32), 16000)
    controller.toggle()

    assert controller.session.state == State.READY
    assert "too short" in controller.window.status.text()
    assert not harness.engine.submissions
    harness.insertion.assert_not_called()


def test_capacity_limit_stops_recording_and_submits_once(harness):
    controller = harness.build()
    controller.toggle()
    harness.recorders[0].limit_reached = True
    controller.tick()
    controller.tick()

    assert controller.session.state == State.PROCESSING
    assert harness.recorders[0].stop_calls == 1
    assert len(harness.engine.submissions) == 1
    assert not harness.recorders[0].held


def test_shutdown_releases_microphone_hotkey_and_engine_once(harness):
    controller = harness.build()
    controller.toggle()
    recorder = harness.recorders[0]
    controller.shutdown()
    controller.shutdown()

    assert not recorder.held
    assert recorder.close_calls == 1
    assert harness.hotkeys[0].stop_calls == 1
    assert harness.engine.close_calls == 1
    assert controller.session.state == State.CLOSED
    assert not controller.timer.isActive()
    controller.toggle()
    controller.handle_event(result("closed-request"))
    harness.insertion.assert_not_called()


def test_constructor_failure_releases_hotkey_and_engine(harness):
    harness.engine.start_error = RuntimeError("Engine startup failed")
    with pytest.raises(RuntimeError, match="Engine startup failed"):
        harness.build(ready=False)

    assert harness.hotkeys[0].start_calls == 1
    assert harness.hotkeys[0].stop_calls == 1
    assert not harness.hotkeys[0].started
    assert harness.engine.close_calls == 1
    assert not harness.recorders


def test_engine_communication_failure_while_recording_releases_microphone(harness):
    controller = harness.build()
    controller.toggle()
    recorder = harness.recorders[0]
    harness.engine.poll_error = RuntimeError("Worker process disappeared")
    controller.tick()

    assert controller.session.state == State.ERROR
    assert not recorder.held
    assert controller.recorder is None
    harness.insertion.assert_not_called()


def test_cancel_processing_handles_worker_restart_failure(harness):
    controller = harness.build()
    request_id = begin_processing(controller)
    harness.engine.start_error = RuntimeError("Worker restart failed")
    controller.cancel()

    assert controller.session.state == State.ERROR
    assert "Worker restart failed" in controller.window.status.text()
    controller.handle_event(result(request_id))
    harness.insertion.assert_not_called()


def test_global_worker_error_closes_active_microphone(harness):
    controller = harness.build()
    controller.toggle()
    recorder = harness.recorders[0]
    controller.handle_event({"kind": "error", "request_id": None, "message": "Worker exited"})

    assert controller.session.state == State.ERROR
    assert not recorder.held
    assert controller.recorder is None
    assert recorder.close_calls == 1


def test_cancel_recording_handles_microphone_close_failure(harness):
    controller = harness.build()
    controller.toggle()
    recorder = harness.recorders[0]
    recorder.close_error = RuntimeError("Microphone close failed")
    controller.cancel()

    assert not recorder.held
    assert controller.recorder is None
    assert controller.session.state == State.READY
    assert controller.session.target is None
    assert controller.session.request_id is None
    harness.insertion.assert_not_called()


def test_failed_hotkey_registration_keeps_preview_and_settings_available(harness):
    harness.hotkey_state.error = NativeError("Shortcut is occupied")
    controller = harness.build()

    assert controller._hotkey_error == "Shortcut is occupied"
    assert harness.engine.start_calls == 1
    assert harness.hotkeys[0].stop_calls == 1
    assert controller.session.state == State.READY
    assert controller.window.settings_button.isEnabled()
    assert controller.window.preview_button.isEnabled()
    assert "Shortcut unavailable" in controller.window.status.text()
    request_id = begin_processing(controller, preview=True)
    controller.handle_event(result(request_id))
    harness.insertion.assert_not_called()


def test_settings_can_recover_previously_failed_hotkey_registration(harness):
    harness.hotkey_state.error = NativeError("Shortcut is occupied")
    controller = harness.build()
    harness.hotkey_state.error = None
    replacement = replace(controller.settings, hotkey="Ctrl+Alt+Shift+F24")
    dialog = SimpleNamespace(exec=lambda: 1, result_settings=replacement)
    harness.monkeypatch.setattr(app_module, "SettingsDialog", Mock(return_value=dialog))
    controller.edit_settings()

    assert controller._hotkey_error is None
    assert controller.hotkey is harness.hotkeys[1]
    assert controller.hotkey.started
    assert controller.settings.hotkey == "Ctrl+Alt+Shift+F24"
    assert controller.settings_path.is_file()
    assert "Shortcut unavailable" not in controller.window.status.text()


def test_settings_hotkey_conflict_preserves_registered_shortcut(harness):
    controller = harness.build()
    original_hotkey = controller.hotkey
    original_settings = controller.settings
    harness.hotkey_state.error = NativeError("Replacement shortcut is occupied")
    replacement = replace(original_settings, hotkey="Ctrl+Alt+Shift+F24")
    dialog = SimpleNamespace(exec=lambda: 1, result_settings=replacement)
    warning = Mock()
    harness.monkeypatch.setattr(app_module, "SettingsDialog", Mock(return_value=dialog))
    harness.monkeypatch.setattr(app_module.QMessageBox, "warning", warning)
    controller.edit_settings()

    assert controller.hotkey is original_hotkey
    assert original_hotkey.started
    assert original_hotkey.stop_calls == 0
    assert controller.settings is original_settings
    assert not controller.settings_path.exists()
    assert harness.hotkeys[1].stop_calls == 1
    warning.assert_called_once()


def test_hotkey_override_is_validated_and_not_saved(harness):
    controller = harness.build(hotkey_override="Ctrl+Alt+Shift+F24")

    assert controller.settings.hotkey == "Ctrl+Alt+Shift+F24"
    assert harness.hotkeys[0].spec == "Ctrl+Alt+Shift+F24"
    assert not controller.settings_path.exists()


def test_shortcut_cannot_start_recording_inside_modal_settings_dialog(harness):
    controller = harness.build()

    def execute_dialog():
        # QDialog.exec() keeps Qt signals flowing, including the global shortcut.
        controller.shortcut_pressed.emit()
        assert controller.session.state == State.READY
        return 1

    dialog = SimpleNamespace(exec=execute_dialog, result_settings=replace(controller.settings, language="de"))
    harness.monkeypatch.setattr(app_module, "SettingsDialog", Mock(return_value=dialog))
    controller.edit_settings()

    harness.capture.assert_not_called()
    assert not harness.recorders
    assert controller.session.state == State.READY
    assert controller.settings.language == "de"


def test_modal_settings_dialog_cannot_open_a_second_settings_dialog(harness):
    controller = harness.build()

    def execute_dialog():
        controller.edit_settings()
        return 0

    dialog = SimpleNamespace(exec=execute_dialog, result_settings=None)
    factory = Mock(return_value=dialog)
    harness.monkeypatch.setattr(app_module, "SettingsDialog", factory)
    controller.edit_settings()

    factory.assert_called_once_with(controller.settings, controller.window)
    assert not harness.recorders
