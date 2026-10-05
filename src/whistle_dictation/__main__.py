from __future__ import annotations

import argparse
import ctypes
import json
import multiprocessing
import platform
import sys
import time
from pathlib import Path

from .runtime import app_directory, configure_environment, download_runtime, verify_runtime


def doctor(root: Path) -> int:
    report = {"python": platform.python_version(), "os": platform.system(),
              "architecture": platform.machine(), "root": str(root), "ok": False}
    try:
        report["runtime"] = verify_runtime(root)
        configure_environment(root)
        import needle
        import numpy as np
        from .audio import input_devices

        started = time.perf_counter()
        model = needle.Whistle(weights=str(root / "models" / "whistle.cact"))
        report["load_seconds"] = round(time.perf_counter() - started, 3)
        report["silence_result"] = model.transcribe(np.zeros(16000, dtype=np.float32), language="en")
        report["microphones"] = input_devices()
        from .win32 import INPUT
        report["input_struct_bytes"] = ctypes.sizeof(INPUT)
        report["ok"] = report["silence_result"]["text"] == ""
    except Exception as exc:
        report["error"] = str(exc)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="Local Windows hotkey dictation with Whistle.")
    parser.add_argument("--root", type=Path, default=app_directory(), help="Portable app directory")
    parser.add_argument("--download-model", action="store_true", help="Download verified runtime; setup only")
    parser.add_argument("--doctor", action="store_true", help="Check native engine and microphone devices")
    parser.add_argument("--hidden", action="store_true", help="Start in the tray")
    parser.add_argument("--hotkey", help="Override the shortcut for this launch")
    parser.add_argument("--smoke-test", action="store_true", help="Offscreen UI/engine test, never record or insert")
    parser.add_argument("--transcribe", type=Path, help="Transcribe a WAV file to stdout without inserting")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.download_model:
        try:
            print(json.dumps(download_runtime(root), indent=2))
            return 0
        except Exception as exc:
            print(f"Setup failed: {exc}", file=sys.stderr)
            return 1
    if args.doctor:
        return doctor(root)
    configure_environment(root)
    if args.transcribe:
        try:
            verify_runtime(root)
            import needle
            print(json.dumps(needle.Whistle(weights=str(root / "models" / "whistle.cact"))
                             .transcribe(str(args.transcribe)), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:
            print(f"Transcription failed: {exc}", file=sys.stderr)
            return 1
    if sys.platform != "win32":
        print("The tray app requires Windows. Pure unit tests can run on other platforms.", file=sys.stderr)
        return 1
    if args.smoke_test:
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
    from .app import TrayApplication, setup_logging
    from .session import State
    from .ui import STYLE
    from .win32 import SingleInstance

    application = QApplication([sys.argv[0]])
    application.setQuitOnLastWindowClosed(False)
    application.setApplicationName("Whistle Dictation")
    application.setStyleSheet(STYLE)
    controller = None
    instance = None
    result = 0
    try:
        if not args.smoke_test and not QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError("A Windows desktop session with a notification tray is required.")
        instance = SingleInstance("Local\\WhistleDictation.Smoke" if args.smoke_test
                                  else "Local\\WhistleDictation.SingleInstance")
        instance.__enter__()
        setup_logging(root)
        controller = TrayApplication(application, root, hidden=args.hidden or args.smoke_test,
            hotkey_override=args.hotkey or ("Ctrl+Alt+Shift+F24" if args.smoke_test else None))
        if args.smoke_test:
            timer = QTimer()
            timer.setInterval(100)
            deadline = time.monotonic() + 30

            def finish_smoke():
                nonlocal result
                if controller.session.state == State.READY and not controller._hotkey_error:
                    print("Smoke test passed: UI, registered hotkey, worker, model load, clean shutdown.")
                    controller.quit()
                elif (controller.session.state == State.ERROR or controller._hotkey_error
                      or time.monotonic() > deadline):
                    print("Smoke test failed: " + controller.window.status.text(), file=sys.stderr)
                    result = 1
                    controller.quit()

            timer.timeout.connect(finish_smoke)
            timer.start()
        application.exec()
    except Exception as exc:
        if args.smoke_test:
            print(str(exc), file=sys.stderr)
        else:
            QMessageBox.critical(None, "Whistle Dictation could not start", str(exc))
        result = 1
    finally:
        if controller:
            controller.shutdown()
        if instance:
            instance.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
