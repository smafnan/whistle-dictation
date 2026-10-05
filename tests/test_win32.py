"""Native boundary tests: no global key registration or typing into a real app."""

from __future__ import annotations

import ctypes
import queue
import threading
import unittest
from unittest.mock import patch

from whistle_dictation import win32


class FakeAPI:
    def __init__(self) -> None:
        self.foreground_hwnd = 100
        self.focused_hwnd = 101
        self.process_ids = {100: 42, 101: 42, 102: 42, 200: 43}
        self.windows = {100, 101, 102, 200}
        self.pressed = False
        self.sent: list[list[tuple[int, int, int, int]]] = []
        self.partial_count: int | None = None
        self.after_send = None
        self.messages: queue.Queue[tuple[int, int, int]] = queue.Queue()
        self.registration_error: Exception | None = None
        self.registered = []
        self.unregistered = []
        self.mutex_exists = False
        self.closed = []

    def foreground(self):
        return self.foreground_hwnd

    def root(self, hwnd):
        return 100 if hwnd in {100, 101, 102} else hwnd

    def is_window(self, hwnd):
        return hwnd in self.windows

    def is_child(self, parent, child):
        return parent == 100 and child in {101, 102}

    def thread_process(self, hwnd):
        return 7, self.process_ids[hwnd]

    def focused(self, _thread):
        return self.focused_hwnd

    def modifiers_down(self):
        return self.pressed

    def send_inputs(self, inputs):
        self.sent.append([(item.type, item.ki.wVk, item.ki.wScan, item.ki.dwFlags) for item in inputs])
        if self.after_send:
            self.after_send()
        return len(inputs) if self.partial_count is None else self.partial_count

    def input_error(self):
        return "fake input failure"

    def prepare_queue(self):
        return 11

    def register_hotkey(self, identifier, hotkey):
        if self.registration_error:
            raise self.registration_error
        self.registered.append((identifier, hotkey))

    def unregister_hotkey(self, identifier):
        self.unregistered.append(identifier)

    def get_message(self):
        return self.messages.get(timeout=2)

    def post_quit(self, _thread_id):
        self.messages.put((0, win32.WM_QUIT, 0))
        return True

    def create_mutex(self, _name):
        return 1234, self.mutex_exists

    def close_handle(self, handle):
        self.closed.append(handle)


class NativeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.patcher = patch.object(win32, "_api", self.api)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.target = win32.FocusTarget(100, 101, 42)

    def test_capture_records_foreground_child_and_process(self):
        self.assertEqual(win32.capture_target(), self.target)

    def test_capture_rejects_missing_focused_control(self):
        self.api.focused_hwnd = 0
        with self.assertRaisesRegex(win32.NativeError, "No focused"):
            win32.capture_target()

    def test_capture_rejects_control_from_another_window(self):
        self.api.focused_hwnd = 200
        with self.assertRaisesRegex(win32.NativeError, "does not belong"):
            win32.capture_target()

    def test_foreground_change_prevents_all_typing(self):
        self.api.foreground_hwnd = 200
        with self.assertRaisesRegex(win32.NativeError, "active window changed"):
            win32.insert_text("private transcript", self.target)
        self.assertEqual(self.api.sent, [])

    def test_child_focus_change_prevents_all_typing(self):
        self.api.focused_hwnd = 102
        with self.assertRaisesRegex(win32.NativeError, "focused text field changed"):
            win32.insert_text("private transcript", self.target)
        self.assertEqual(self.api.sent, [])

    def test_process_change_prevents_reused_hwnd_receiving_text(self):
        self.api.process_ids[101] = 88
        with self.assertRaisesRegex(win32.NativeError, "changed process"):
            win32.insert_text("private transcript", self.target)
        self.assertEqual(self.api.sent, [])

    def test_closed_window_prevents_typing(self):
        self.api.windows.remove(100)
        with self.assertRaisesRegex(win32.NativeError, "closed"):
            win32.insert_text("private transcript", self.target)
        self.assertEqual(self.api.sent, [])

    def test_unicode_handles_bmp_and_supplementary_characters(self):
        win32.insert_text("Aä😀", self.target)
        events = self.api.sent[0]
        self.assertEqual(
            [(scan, flags) for _, _, scan, flags in events],
            [(65, 4), (65, 6), (228, 4), (228, 6), (0xD83D, 4), (0xDE00, 4), (0xD83D, 6), (0xDE00, 6)],
        )
        self.assertTrue(all(kind == win32.INPUT_KEYBOARD and vk == 0 for kind, vk, _, _ in events))

    def test_surrogate_pair_remains_in_one_bounded_chunk(self):
        chunks = list(win32._unicode_chunks("a😀b", max_units=2))
        self.assertEqual([len(chunk) for chunk in chunks], [2, 4, 2])
        self.assertEqual([scan for scan, flags in chunks[1] if flags == 4], [0xD83D, 0xDE00])

    def test_newline_or_controls_are_rejected_before_any_typing(self):
        for text in ("hello\nworld", "hello\rworld", "hello\tworld", "hello\x00world", "hello\u2028world"):
            with self.subTest(text=repr(text)):
                with self.assertRaisesRegex(win32.NativeError, "single line"):
                    win32.insert_text(text, self.target)
        self.assertEqual(self.api.sent, [])

    def test_invalid_surrogate_is_rejected_before_any_typing(self):
        with self.assertRaisesRegex(win32.NativeError, "invalid Unicode"):
            win32.insert_text("a" * 300 + "\ud800", self.target)
        self.assertEqual(self.api.sent, [])

    def test_focus_change_during_first_chunk_stops_later_chunks(self):
        self.api.after_send = lambda: setattr(self.api, "focused_hwnd", 102)
        with self.assertRaisesRegex(win32.NativeError, "focused text field changed"):
            win32.insert_text("a" * 300, self.target)
        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(len(self.api.sent[0]), 256)

    def test_partial_send_is_reported_and_never_retried(self):
        self.api.partial_count = 1
        with self.assertRaisesRegex(win32.NativeError, "1 of 6 input events"):
            win32.insert_text("abc", self.target)
        self.assertEqual(len(self.api.sent), 1)

    def test_held_modifiers_timeout_without_typing(self):
        self.api.pressed = True
        with self.assertRaisesRegex(win32.NativeError, "Release Ctrl"):
            win32.insert_text("abc", self.target, modifier_timeout=0)
        self.assertEqual(self.api.sent, [])

    def test_modifier_release_is_waited_for(self):
        self.api.pressed = True
        with patch.object(win32.time, "sleep", side_effect=lambda _: setattr(self.api, "pressed", False)):
            win32.insert_text("abc", self.target)
        self.assertEqual(len(self.api.sent), 1)

    def test_modifier_wait_requires_a_bounded_timeout(self):
        for timeout in (-1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(ValueError, "finite"):
                    win32.insert_text("abc", self.target, modifier_timeout=timeout)
        self.assertEqual(self.api.sent, [])

    def test_registration_error_is_synchronous(self):
        self.api.registration_error = win32.NativeError("Shortcut already in use")
        listener = win32.GlobalHotkey("Ctrl+Alt+Space", lambda: None)
        self.addCleanup(listener.stop)
        with self.assertRaisesRegex(win32.NativeError, "already in use"):
            listener.start()
        self.assertFalse(listener._thread.is_alive())

    def test_hotkey_thread_dispatches_only_matching_hotkey(self):
        triggered = threading.Event()
        listener = win32.GlobalHotkey("Ctrl+Alt+Space", triggered.set)
        self.addCleanup(listener.stop)
        listener.start()
        self.api.messages.put((1, win32.WM_HOTKEY, 2))
        self.api.messages.put((1, win32.WM_HOTKEY, 1))
        self.assertTrue(triggered.wait(1))
        listener.stop()
        self.assertEqual(self.api.unregistered, [1])
        self.assertFalse(listener._thread.is_alive())

    def test_second_instance_closes_its_handle_and_fails(self):
        self.api.mutex_exists = True
        with self.assertRaisesRegex(win32.NativeError, "already running"):
            with win32.SingleInstance():
                self.fail("Duplicate instance must not enter")
        self.assertEqual(self.api.closed, [1234])

    def test_instance_context_closes_handle_once_even_on_failure(self):
        instance = win32.SingleInstance()
        with self.assertRaisesRegex(ValueError, "application failed"):
            with instance:
                raise ValueError("application failed")
        instance.close()
        self.assertEqual(self.api.closed, [1234])


class PureNativeHelperTests(unittest.TestCase):
    def test_hotkey_canonicalization_and_virtual_key(self):
        parsed = win32.parse_hotkey(" shift + CONTROL + alt + space ")
        self.assertEqual(parsed.canonical, "Ctrl+Alt+Shift+Space")
        self.assertEqual(parsed.modifiers, 7)
        self.assertEqual(parsed.vkey, 32)
        self.assertEqual(win32.parse_hotkey("Alt+f24").vkey, 0x87)

    def test_invalid_hotkeys_are_rejected(self):
        for spec in ("", "Space", "Shift+A", "Ctrl+", "Ctrl+Ctrl+A", "Ctrl+A+B", "Win+A", "Ctrl+F12", "Alt+F012", "Alt+F25", "Ctrl+ä"):
            with self.subTest(spec=spec):
                with self.assertRaises(win32.NativeError):
                    win32.parse_hotkey(spec)

    def test_input_structures_use_windows_abi_sizes(self):
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(win32.MOUSEINPUT), 32)
            self.assertEqual(ctypes.sizeof(win32.KEYBDINPUT), 24)
            self.assertEqual(ctypes.sizeof(win32.INPUT), 40)
            self.assertEqual(ctypes.sizeof(win32.GUITHREADINFO), 72)
            self.assertEqual(ctypes.sizeof(win32.MSG), 48)
        else:
            self.assertEqual(ctypes.sizeof(win32.INPUT), 28)
            self.assertEqual(ctypes.sizeof(win32.KEYBDINPUT), 16)


if __name__ == "__main__":
    unittest.main()
