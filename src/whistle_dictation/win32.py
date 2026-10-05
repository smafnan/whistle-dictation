"""Small, pointer-safe Win32 integration for focus-preserving dictation.

Importing this module does not load Windows DLLs. The pure hotkey and Unicode
helpers can therefore be tested on any platform. Text delivery deliberately
does not activate a window, synthesize shortcuts, or touch the clipboard.
"""

from __future__ import annotations

import ctypes
import logging
import math
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Callable, Iterator


class NativeError(RuntimeError):
    """A native operation failed or its preconditions no longer hold."""


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1
GA_ROOT = 2
ERROR_ALREADY_EXISTS = 183
_MODIFIER_KEYS = (0x10, 0x11, 0x12, 0x5B, 0x5C)
_LOG = logging.getLogger(__name__)


# Windows LONG/DWORD have fixed widths even where the host's C long does not.
DWORD = ctypes.c_uint32
LONG = ctypes.c_int32
WORD = ctypes.c_uint16
UINT = ctypes.c_uint32
BOOL = ctypes.c_int32
HWND = ctypes.c_void_p
HANDLE = ctypes.c_void_p
ULONG_PTR = ctypes.c_size_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t


class POINT(ctypes.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class RECT(ctypes.Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("flags", DWORD),
        ("hwndActive", HWND),
        ("hwndFocus", HWND),
        ("hwndCapture", HWND),
        ("hwndMenuOwner", HWND),
        ("hwndMoveSize", HWND),
        ("hwndCaret", HWND),
        ("rcCaret", RECT),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", LONG),
        ("dy", LONG),
        ("mouseData", DWORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", WORD),
        ("wScan", WORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", DWORD), ("u", _INPUTUNION)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", HWND),
        ("message", UINT),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", DWORD),
        ("pt", POINT),
        ("lPrivate", DWORD),
    ]


@dataclass(frozen=True)
class FocusTarget:
    hwnd: int
    focused_hwnd: int
    process_id: int


@dataclass(frozen=True)
class Hotkey:
    modifiers: int
    vkey: int
    canonical: str


_NAMED_KEYS = {
    "space": (0x20, "Space"),
    "tab": (0x09, "Tab"),
    "enter": (0x0D, "Enter"),
    "return": (0x0D, "Enter"),
    "escape": (0x1B, "Escape"),
    "esc": (0x1B, "Escape"),
    "backspace": (0x08, "Backspace"),
    "insert": (0x2D, "Insert"),
    "delete": (0x2E, "Delete"),
    "home": (0x24, "Home"),
    "end": (0x23, "End"),
    "pageup": (0x21, "PageUp"),
    "pagedown": (0x22, "PageDown"),
    "left": (0x25, "Left"),
    "up": (0x26, "Up"),
    "right": (0x27, "Right"),
    "down": (0x28, "Down"),
    "pause": (0x13, "Pause"),
}
_MODIFIER_NAMES = {
    "ctrl": (MOD_CONTROL, "Ctrl"),
    "control": (MOD_CONTROL, "Ctrl"),
    "alt": (MOD_ALT, "Alt"),
    "shift": (MOD_SHIFT, "Shift"),
}


def parse_hotkey(spec: str = "Ctrl+Alt+Space") -> Hotkey:
    """Parse a global shortcut; avoid system-reserved Windows/F12 shortcuts."""
    if not isinstance(spec, str) or not spec.strip():
        raise NativeError("Enter a hotkey such as Ctrl+Alt+Space.")
    pieces = [part.strip().lower() for part in spec.split("+")]
    if any(not piece for piece in pieces):
        raise NativeError("The hotkey contains an empty key name.")
    modifiers = 0
    keys: list[str] = []
    for piece in pieces:
        if piece in {"win", "windows", "super", "meta"}:
            raise NativeError("Windows-key shortcuts are reserved by Windows.")
        if piece in _MODIFIER_NAMES:
            flag, name = _MODIFIER_NAMES[piece]
            if modifiers & flag:
                raise NativeError(f"The hotkey repeats the {name} modifier.")
            modifiers |= flag
        else:
            keys.append(piece)
    if len(keys) != 1:
        raise NativeError("The hotkey must contain exactly one non-modifier key.")
    if not modifiers & (MOD_CONTROL | MOD_ALT):
        raise NativeError("The hotkey must include Ctrl or Alt.")
    key = keys[0]
    if key == "f12":
        raise NativeError("F12 is reserved by the Windows debugger.")
    if key in _NAMED_KEYS:
        vkey, name = _NAMED_KEYS[key]
    elif len(key) == 1 and key.isascii() and key.isalnum():
        name = key.upper()
        vkey = ord(name)
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        number = int(key[1:])
        if number == 12:
            raise NativeError("F12 is reserved by the Windows debugger.")
        name = f"F{number}"
        vkey = 0x70 + number - 1
    else:
        raise NativeError(f"Unsupported hotkey key: {key}.")
    names = [
        name
        for flag, name in ((MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift"))
        if modifiers & flag
    ]
    return Hotkey(modifiers, vkey, "+".join([*names, name]))


def _native_failure(operation: str) -> NativeError:
    code = ctypes.get_last_error()
    detail = ctypes.FormatError(code).strip() if code else "Windows did not report an error code"
    return NativeError(f"{operation} failed ({code}: {detail}).")


class _Win32API:
    """Typed DLL bindings with a compact, fakeable boundary for unit tests."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise NativeError("Global hotkeys and text insertion require Windows.")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = [
            (self.user32, "GetForegroundWindow", [], HWND),
            (self.user32, "GetAncestor", [HWND, UINT], HWND),
            (self.user32, "IsWindow", [HWND], BOOL),
            (self.user32, "IsChild", [HWND, HWND], BOOL),
            (self.user32, "GetWindowThreadProcessId", [HWND, ctypes.POINTER(DWORD)], DWORD),
            (self.user32, "GetGUIThreadInfo", [DWORD, ctypes.POINTER(GUITHREADINFO)], BOOL),
            (self.user32, "GetAsyncKeyState", [ctypes.c_int], ctypes.c_int16),
            (self.user32, "SendInput", [UINT, ctypes.POINTER(INPUT), ctypes.c_int], UINT),
            (self.user32, "RegisterHotKey", [HWND, ctypes.c_int, UINT, UINT], BOOL),
            (self.user32, "UnregisterHotKey", [HWND, ctypes.c_int], BOOL),
            (self.user32, "PeekMessageW", [ctypes.POINTER(MSG), HWND, UINT, UINT, UINT], BOOL),
            (self.user32, "GetMessageW", [ctypes.POINTER(MSG), HWND, UINT, UINT], BOOL),
            (self.user32, "PostThreadMessageW", [DWORD, UINT, WPARAM, LPARAM], BOOL),
            (self.kernel32, "GetCurrentThreadId", [], DWORD),
            (self.kernel32, "CreateMutexW", [ctypes.c_void_p, BOOL, ctypes.c_wchar_p], HANDLE),
            (self.kernel32, "CloseHandle", [HANDLE], BOOL),
        ]
        for library, name, argtypes, restype in signatures:
            function = getattr(library, name)
            function.argtypes = argtypes
            function.restype = restype

    def foreground(self) -> int:
        return int(self.user32.GetForegroundWindow() or 0)

    def root(self, hwnd: int) -> int:
        return int(self.user32.GetAncestor(hwnd, GA_ROOT) or 0)

    def is_window(self, hwnd: int) -> bool:
        return bool(hwnd and self.user32.IsWindow(hwnd))

    def is_child(self, parent: int, child: int) -> bool:
        return bool(self.user32.IsChild(parent, child))

    def thread_process(self, hwnd: int) -> tuple[int, int]:
        process = DWORD()
        thread = self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
        if not thread:
            raise _native_failure("Reading the target window")
        return int(thread), int(process.value)

    def focused(self, thread_id: int) -> int:
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        if not self.user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            raise _native_failure("Reading keyboard focus")
        # Menus and move/resize loops are not a text entry destination.
        if info.flags & (0x02 | 0x04 | 0x08 | 0x10):
            raise NativeError("Close the active menu or window move operation before dictating.")
        return int(info.hwndFocus or 0)

    def modifiers_down(self) -> bool:
        return any(self.user32.GetAsyncKeyState(key) & 0x8000 for key in _MODIFIER_KEYS)

    def send_inputs(self, inputs: ctypes.Array[INPUT]) -> int:
        ctypes.set_last_error(0)
        return int(self.user32.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT)))

    def input_error(self) -> str:
        code = ctypes.get_last_error()
        return f"Windows error {code}" if code else "Windows may have blocked input into an elevated application"

    def prepare_queue(self) -> int:
        message = MSG()
        self.user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
        return int(self.kernel32.GetCurrentThreadId())

    def register_hotkey(self, identifier: int, hotkey: Hotkey) -> None:
        if not self.user32.RegisterHotKey(None, identifier, hotkey.modifiers | MOD_NOREPEAT, hotkey.vkey):
            error = _native_failure(f"Registering {hotkey.canonical}")
            raise NativeError(f"{error} Choose a shortcut that another application is not using.")

    def unregister_hotkey(self, identifier: int) -> None:
        self.user32.UnregisterHotKey(None, identifier)

    def get_message(self) -> tuple[int, int, int]:
        message = MSG()
        result = int(self.user32.GetMessageW(ctypes.byref(message), None, 0, 0))
        if result == -1:
            raise _native_failure("Reading global hotkey messages")
        return result, int(message.message), int(message.wParam)

    def post_quit(self, thread_id: int) -> bool:
        return bool(self.user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0))

    def create_mutex(self, name: str) -> tuple[int, bool]:
        ctypes.set_last_error(0)
        handle = self.kernel32.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()
        if not handle:
            raise _native_failure("Creating the application instance lock")
        return int(handle), error == ERROR_ALREADY_EXISTS

    def close_handle(self, handle: int) -> None:
        self.kernel32.CloseHandle(handle)


_api: _Win32API | None = None
_api_lock = threading.Lock()


def _get_api() -> _Win32API:
    global _api
    with _api_lock:
        if _api is None:
            _api = _Win32API()
        return _api


def capture_target() -> FocusTarget:
    """Capture the currently focused child without activating any window."""
    api = _get_api()
    foreground = api.foreground()
    root = api.root(foreground) if foreground else 0
    if not root or not api.is_window(root):
        raise NativeError("Select a text field before starting dictation.")
    thread_id, root_pid = api.thread_process(root)
    focused = api.focused(thread_id)
    if not focused or not api.is_window(focused):
        raise NativeError("No focused text destination was found. Select a text field first.")
    if focused != root and not api.is_child(root, focused):
        raise NativeError("The focused control does not belong to the active window.")
    _, process_id = api.thread_process(focused)
    if process_id != root_pid:
        raise NativeError("The focused control changed process while capturing the target.")
    target = FocusTarget(root, focused, process_id)
    ensure_target(target)
    return target


def ensure_target(target: FocusTarget) -> None:
    """Fail closed if the foreground window, child focus, or process changed."""
    api = _get_api()
    if not api.is_window(target.hwnd) or not api.is_window(target.focused_hwnd):
        raise NativeError("The original text destination has closed; text insertion was stopped.")
    foreground = api.foreground()
    if not foreground or api.root(foreground) != target.hwnd:
        raise NativeError("The active window changed; text insertion was stopped.")
    thread_id, process_id = api.thread_process(target.hwnd)
    if process_id != target.process_id:
        raise NativeError("The original window changed process; text insertion was stopped.")
    if api.focused(thread_id) != target.focused_hwnd:
        raise NativeError("The focused text field changed; text insertion was stopped.")
    if target.focused_hwnd != target.hwnd and not api.is_child(target.hwnd, target.focused_hwnd):
        raise NativeError("The original text field moved to another window.")
    _, focused_pid = api.thread_process(target.focused_hwnd)
    if focused_pid != target.process_id:
        raise NativeError("The text field changed process; text insertion was stopped.")


def _unicode_chunks(text: str, max_units: int = 128) -> Iterator[tuple[tuple[int, int], ...]]:
    """Yield bounded UTF-16 input packets without splitting a surrogate pair."""
    if max_units < 2:
        raise ValueError("A Unicode chunk must have room for a surrogate pair.")
    # Validate the entire string before producing any packets.
    if any(unicodedata.category(char) == "Cc" or char in "\u2028\u2029" for char in text):
        raise NativeError("Text insertion accepts a single line without control characters.")
    try:
        text.encode("utf-16-le")
    except UnicodeEncodeError as error:
        raise NativeError("The transcript contains an invalid Unicode surrogate.") from error
    events: list[tuple[int, int]] = []
    unit_count = 0
    for char in text:
        encoded = char.encode("utf-16-le")
        units = [int.from_bytes(encoded[offset : offset + 2], "little") for offset in range(0, len(encoded), 2)]
        if unit_count + len(units) > max_units:
            yield tuple(events)
            events = []
            unit_count = 0
        events.extend((unit, KEYEVENTF_UNICODE) for unit in units)
        events.extend((unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP) for unit in units)
        unit_count += len(units)
    if events:
        yield tuple(events)


def _build_inputs(events: tuple[tuple[int, int], ...]) -> ctypes.Array[INPUT]:
    inputs = (INPUT * len(events))()
    for item, (unit, flags) in zip(inputs, events, strict=True):
        item.type = INPUT_KEYBOARD
        item.ki = KEYBDINPUT(0, unit, flags, 0, 0)
    return inputs


def _wait_for_modifiers(target: FocusTarget, timeout: float) -> None:
    api = _get_api()
    deadline = time.monotonic() + timeout
    while api.modifiers_down():
        ensure_target(target)
        if time.monotonic() >= deadline:
            raise NativeError("Release Ctrl, Alt, Shift, and the Windows key before inserting text.")
        time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))


def insert_text(text: str, target: FocusTarget, modifier_timeout: float = 1.5) -> None:
    """Insert Unicode into unchanged focus, with no clipboard or Enter key.

    SendInput can be rejected by Windows integrity restrictions. A partial send
    is reported and never retried: retrying could duplicate already typed text.
    Focus checks bound the risk but cannot make Windows input delivery atomic.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not math.isfinite(modifier_timeout) or modifier_timeout < 0:
        raise ValueError("modifier_timeout must be finite and not negative")
    api = _get_api()
    for events in _unicode_chunks(text):
        _wait_for_modifiers(target, modifier_timeout)
        ensure_target(target)
        inputs = _build_inputs(events)
        inserted = api.send_inputs(inputs)
        if inserted != len(inputs):
            raise NativeError(
                f"Text delivery stopped after {inserted} of {len(inputs)} input events: "
                f"{api.input_error()}. Some text may already have been entered; automatic retry is disabled."
            )
        ensure_target(target)


class GlobalHotkey:
    """Register a shortcut on a dedicated native message-loop thread.

    on_trigger executes on that thread; Qt callers should emit a queued signal.
    Registration errors are raised synchronously by start(), within three seconds.
    """

    _IDENTIFIER = 1

    def __init__(self, spec: str, on_trigger: Callable[[], None]) -> None:
        self.hotkey = parse_hotkey(spec)
        if not callable(on_trigger):
            raise TypeError("on_trigger must be callable")
        self.on_trigger = on_trigger
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._error: BaseException | None = None
        self._lifecycle_lock = threading.Lock()

    @property
    def spec(self) -> str:
        return self.hotkey.canonical

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                if self._stop.is_set():
                    raise NativeError("The previous hotkey listener is still stopping.")
                return
            self._ready.clear()
            self._stop.clear()
            self._error = None
            self._thread_id = 0
            self._thread = threading.Thread(target=self._run, name="whistle-global-hotkey", daemon=True)
            self._thread.start()
        if not self._ready.wait(3.0):
            # Do not add stop()'s one-second join to the startup deadline.
            self._request_stop()
            raise NativeError("Timed out registering the global hotkey.")
        if self._error is not None:
            error = self._error
            self.stop()
            if isinstance(error, NativeError):
                raise error
            raise NativeError(f"Unable to start the global hotkey: {error}") from error

    def _run(self) -> None:
        registered = False
        api: _Win32API | None = None
        try:
            api = _get_api()
            self._thread_id = api.prepare_queue()
            api.register_hotkey(self._IDENTIFIER, self.hotkey)
            registered = True
            self._ready.set()
            while not self._stop.is_set():
                result, message, parameter = api.get_message()
                if result == 0:
                    break
                if message == WM_HOTKEY and parameter == self._IDENTIFIER and not self._stop.is_set():
                    try:
                        self.on_trigger()
                    except Exception:
                        _LOG.exception("Global hotkey callback failed")
        except Exception as error:
            self._error = error
            _LOG.error("Global hotkey listener failed: %s", error)
        finally:
            try:
                if registered and api is not None:
                    api.unregister_hotkey(self._IDENTIFIER)
            finally:
                self._thread_id = 0
                self._ready.set()

    def _request_stop(self) -> None:
        self._stop.set()
        thread = self._thread
        thread_id = self._thread_id
        if thread_id and thread and thread.is_alive():
            _get_api().post_quit(thread_id)

    def stop(self) -> None:
        self._request_stop()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def __enter__(self) -> GlobalHotkey:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


class SingleInstance:
    """Hold a per-Windows-session instance mutex until the context exits."""

    def __init__(self, name: str = "Local\\WhistleDictation.SingleInstance") -> None:
        if not name or "\x00" in name:
            raise ValueError("The instance mutex name must be nonempty and contain no NUL.")
        self.name = name
        self._handle = 0

    def __enter__(self) -> SingleInstance:
        if self._handle:
            return self
        api = _get_api()
        handle, exists = api.create_mutex(self.name)
        if exists:
            api.close_handle(handle)
            raise NativeError("Whistle Dictation is already running in this Windows session.")
        self._handle = handle
        return self

    def close(self) -> None:
        if self._handle:
            _get_api().close_handle(self._handle)
            self._handle = 0

    def __exit__(self, *_: object) -> None:
        self.close()
