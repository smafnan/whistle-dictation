"""PyInstaller entry point; keep multiprocessing bootstrap before GUI creation."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from whistle_dictation.__main__ import main

    raise SystemExit(main())
