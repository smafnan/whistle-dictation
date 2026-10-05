"""One model, one isolated process; never invoke the native engine on the GUI thread."""
from __future__ import annotations

import multiprocessing as mp
from multiprocessing import shared_memory
import queue
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

import numpy as np

from .audio import MAX_CAPTURE_SAMPLES, CapturedAudio, is_silent, split_audio, to_16khz
from .config import Settings
from .runtime import configure_environment, verify_runtime
from .text import format_transcript

MAX_AUDIO_BYTES = MAX_CAPTURE_SAMPLES * np.dtype(np.float32).itemsize


def transcribe_recording(model, captured: CapturedAudio, settings: Settings,
                         progress: Callable[[int, int], None] | None = None) -> dict:
    started = time.perf_counter()
    samples = to_16khz(captured)
    if is_silent(samples):
        return {"text": "", "seconds": time.perf_counter() - started, "chunks": 0}
    chunks = split_audio(samples)
    texts = []
    for index, chunk in enumerate(chunks, 1):
        if not is_silent(chunk):
            result = model.transcribe(chunk, language=settings.language, keywords=settings.keywords)
            if not isinstance(result, dict) or not isinstance(result.get("text"), str):
                raise RuntimeError("Whistle returned an invalid transcript.")
            texts.append(result["text"].strip())
        if progress:
            progress(index, len(chunks))
    return {"text": format_transcript(" ".join(texts), settings),
            "seconds": time.perf_counter() - started, "chunks": len(chunks)}


def worker_main(root: str, requests, responses) -> None:
    try:
        directory = Path(root)
        configure_environment(directory)
        verify_runtime(directory)
        import needle

        model = needle.Whistle(weights=str(directory / "models" / "whistle.cact"))
        responses.put({"kind": "ready"})
    except Exception as exc:
        responses.put({"kind": "error", "request_id": None, "message": str(exc)})
        return
    while True:
        task = requests.get()
        if task is None:
            return
        request_id = task["request_id"]
        attachment = None
        samples = captured = None
        try:
            count = task["sample_count"]
            if type(count) is not int or not 0 < count * 4 <= MAX_AUDIO_BYTES:
                raise RuntimeError("Audio transport contains an invalid sample count.")
            attachment = shared_memory.SharedMemory(name=task["audio_name"])
            if count * 4 > attachment.size:
                raise RuntimeError("Audio transport is smaller than its sample count.")
            samples = np.ndarray((count,), dtype=np.float32, buffer=attachment.buf)
            samples.flags.writeable = False
            captured = CapturedAudio(samples, task["sample_rate"], task["overflow"])
            result = transcribe_recording(model, captured, Settings(**task["settings"]),
                lambda current, total, job=request_id: responses.put({"kind": "progress", "request_id": job,
                                                       "current": current, "total": total}))
            message = {"kind": "result", "request_id": request_id, **result}
        except Exception as exc:
            message = {"kind": "error", "request_id": request_id, "message": str(exc)}
            # An exception retained by a model/test double must not retain audio views.
            exc.__traceback__ = None
        finally:
            # No array view may outlive the attached mapping. The parent owns unlinking.
            captured = samples = None
            if attachment is not None:
                attachment.close()
        responses.put(message)


class EngineService:
    def __init__(self, root: Path):
        self.root = root
        self._context = mp.get_context("spawn")
        self._process = None
        self._requests = None
        self._responses = None
        self._audio_memory: shared_memory.SharedMemory | None = None
        self._pending: str | None = None
        self._deadline = 0.0
        self.ready = False

    def start(self) -> None:
        self.close()
        self._requests = self._context.Queue(maxsize=1)
        self._responses = self._context.Queue()
        # Suppress expected broken pipes when cancelling a worker mid-command.
        # Set this before either process starts a Queue feeder thread.
        for connection in (self._requests, self._responses):
            if hasattr(connection, "_ignore_epipe"):
                connection._ignore_epipe = True
        self._process = self._context.Process(target=worker_main,
                args=(str(self.root), self._requests, self._responses), daemon=True)
        self._process.start()
        self._deadline = time.monotonic() + 90

    def submit(self, request_id: str, captured: CapturedAudio, settings: Settings) -> None:
        if not self.ready or self._pending is not None:
            raise RuntimeError("Speech engine is busy or is not ready.")
        source = np.asarray(captured.samples)
        if source.ndim != 1:
            raise RuntimeError("Audio must contain one mono channel.")
        if not len(source):
            raise RuntimeError("No audio was captured.")
        if source.size * 4 > MAX_AUDIO_BYTES:
            raise RuntimeError("Recording exceeds the 96 MB audio transport limit; record a shorter clip.")
        if (isinstance(captured.sample_rate, bool)
                or not isinstance(captured.sample_rate, (int, np.integer))
                or captured.sample_rate <= 0):
            raise RuntimeError("Audio sample rate must be a positive integer.")
        samples = np.ascontiguousarray(source, dtype=np.float32)
        if not np.isfinite(samples).all():
            raise RuntimeError("Audio contains invalid samples.")
        try:
            memory = shared_memory.SharedMemory(create=True, size=samples.nbytes)
            self._audio_memory = memory
            destination = np.ndarray(samples.shape, dtype=np.float32, buffer=memory.buf)
            try:
                destination[:] = samples
            finally:
                del destination
            # Only bounded control metadata enters the queue; never pickle audio.
            self._requests.put_nowait({"request_id": request_id, "audio_name": memory.name,
                "sample_count": len(samples), "sample_rate": int(captured.sample_rate),
                "overflow": captured.overflow, "settings": asdict(settings)})
        except Exception:
            self._release_audio()
            raise
        self._pending = request_id
        self._deadline = time.monotonic() + settings.inference_timeout_seconds

    def _release_audio(self) -> None:
        memory, self._audio_memory = self._audio_memory, None
        if memory is not None:
            try:
                memory.close()
            finally:
                memory.unlink()

    def poll(self) -> list[dict]:
        if self._process is None:
            return []
        messages = []
        while True:
            try:
                message = self._responses.get_nowait()
            except queue.Empty:
                break
            messages.append(message)
            if message["kind"] == "ready":
                self.ready = True
                self._deadline = 0
            elif message["kind"] in ("result", "error"):
                if message.get("request_id") == self._pending:
                    self._release_audio()
                    self._pending = None
                    self._deadline = 0
        if self._deadline and time.monotonic() > self._deadline:
            messages.append({"kind": "error", "request_id": self._pending,
                             "message": "Speech engine timed out. Use Retry engine to restart it."})
            self.close()
        elif not self._process.is_alive():
            # A handled startup error already carries its useful message.
            if not any(message["kind"] == "error" for message in messages):
                messages.append({"kind": "error", "request_id": self._pending,
                                 "message": "Speech engine stopped unexpectedly. Use Retry engine."})
            self.close()
        return messages

    def close(self) -> None:
        self.ready = False
        if self._process is not None:
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=2)
                if self._process.is_alive():
                    self._process.kill()
                    self._process.join(timeout=1)
            self._process.close()
            self._process = None
        self._release_audio()
        for connection in (self._requests, self._responses):
            if connection is not None:
                connection.cancel_join_thread()
                # Queue.close() only closes the feeder's writer asynchronously. Its
                # parent's unused reader would otherwise keep a blocked write alive
                # after the worker is killed, even for a large settings dictionary.
                # Close the reader BEFORE scheduling the feeder's close sentinel to
                # prevent concurrent CloseHandle calls on the same Windows handle.
                reader = getattr(connection, "_reader", None)
                if reader is not None:
                    reader.close()
                connection.close()
                feeder = getattr(connection, "_thread", None)
                if feeder is not None:
                    feeder.join(timeout=0.5)
                writer = getattr(connection, "_writer", None)
                if writer is not None and (feeder is None or not feeder.is_alive()):
                    writer.close()
        self._requests = self._responses = None
        self._pending = None
        self._deadline = 0
