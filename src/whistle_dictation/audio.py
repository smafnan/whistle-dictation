"""Microphone capture and lossless segmentation for Whistle's clip interface.

Device access and resampling dependencies are loaded only when needed. Capture
callbacks do no device management; the UI calls ``stop`` when ``limit_reached``
becomes true. This keeps PortAudio operations out of its realtime callback.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import math
import threading
from typing import Any

import numpy as np


# Bound native-rate recording storage to 96 MB before concatenation/IPC copies.
MAX_CAPTURE_SAMPLES = 24_000_000


@dataclass(frozen=True)
class CapturedAudio:
    """Mono float32 samples at the microphone's native sample rate."""

    samples: np.ndarray
    sample_rate: int
    overflow: bool = False

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate


def _mono(samples: np.ndarray) -> np.ndarray:
    result = np.asarray(samples, dtype=np.float32)
    if result.ndim != 1:
        raise ValueError("Audio must contain one mono channel.")
    return result


def _rate(sample_rate: int) -> int:
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, (int, np.integer)):
        raise ValueError("Sample rate must be a positive integer.")
    if sample_rate <= 0:
        raise ValueError("Sample rate must be a positive integer.")
    return int(sample_rate)


def input_devices() -> list[dict[str, Any]]:
    """Return only devices with input channels, preserving PortAudio indices."""
    sounddevice = importlib.import_module("sounddevice")
    return [
        {
            "index": index,
            "name": str(device["name"]),
            "sample_rate": int(round(device["default_samplerate"])),
        }
        for index, device in enumerate(sounddevice.query_devices())
        if device["max_input_channels"] > 0
    ]


class MicrophoneRecorder:
    """Bounded microphone recorder; at most one stream exists per instance.

    ``elapsed`` is the captured audio duration, including after ``stop``. A
    capture can last 1..3600 seconds, subject to a 24-million-sample memory cap;
    incoming samples beyond either limit are discarded until the owner observes
    ``limit_reached`` and stops the stream.
    ``close`` aborts and discards audio and is safe to call repeatedly.
    """

    def __init__(self, device: int | None = None, max_seconds: int = 300) -> None:
        if isinstance(max_seconds, bool) or not isinstance(max_seconds, int):
            raise ValueError("max_seconds must be an integer from 1 to 3600.")
        if not 1 <= max_seconds <= 3600:
            raise ValueError("max_seconds must be an integer from 1 to 3600.")
        if device is not None and (
            isinstance(device, bool) or not isinstance(device, int) or device < 0
        ):
            raise ValueError("device must be a nonnegative device index or None.")
        self.device = device
        self.max_seconds = max_seconds
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._stream: Any = None
        self._recording = False
        self._chunks: list[np.ndarray] = []
        self._sample_count = 0
        self._sample_rate = 0
        self._max_samples = 0
        self._overflow = False
        self._limit_reached = False
        self._capture_error: Exception | None = None

    @property
    def elapsed(self) -> float:
        with self._lock:
            return self._sample_count / self._sample_rate if self._sample_rate else 0.0

    @property
    def limit_reached(self) -> bool:
        with self._lock:
            return self._limit_reached

    def start(self) -> None:
        with self._lifecycle_lock:
            with self._lock:
                if self._recording or self._stream is not None:
                    raise RuntimeError("Microphone is already recording.")
            sounddevice = importlib.import_module("sounddevice")
            device = sounddevice.query_devices(self.device, "input")
            if device["max_input_channels"] < 1:
                raise RuntimeError("The selected device has no microphone input.")
            rate = float(device["default_samplerate"])
            if not math.isfinite(rate) or rate <= 0:
                raise RuntimeError("The microphone reported an invalid sample rate.")
            sample_rate = int(round(rate))
            if sample_rate < 1:
                raise RuntimeError("The microphone reported an invalid sample rate.")
            stream = sounddevice.InputStream(
                device=self.device,
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                callback=self._callback,
            )
            with self._lock:
                self._chunks = []
                self._sample_count = 0
                self._sample_rate = sample_rate
                self._max_samples = min(sample_rate * self.max_seconds, MAX_CAPTURE_SAMPLES)
                self._overflow = False
                self._limit_reached = False
                self._capture_error = None
                self._stream = stream
                self._recording = True
            try:
                stream.start()
            except Exception:
                with self._lock:
                    self._recording = False
                    self._stream = None
                    self._chunks = []
                    self._sample_count = 0
                try:
                    stream.close()
                except Exception:
                    pass
                raise

    def _callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        del time_info
        with self._lock:
            if not self._recording:
                return
            self._overflow |= bool(getattr(status, "input_overflow", False))
            if self._limit_reached:
                return
            try:
                remaining = self._max_samples - self._sample_count
                count = min(frames, len(indata), remaining)
                if count > 0:
                    # PortAudio reuses indata's storage after this callback returns.
                    chunk = np.array(indata[:count, 0], dtype=np.float32, copy=True)
                    self._chunks.append(chunk)
                    self._sample_count += count
                self._limit_reached = self._sample_count >= self._max_samples
            except Exception as error:
                # The owner will surface the callback failure from stop().
                self._capture_error = error
                self._limit_reached = True

    def stop(self) -> CapturedAudio:
        with self._lifecycle_lock:
            with self._lock:
                if self._stream is None:
                    raise RuntimeError("Microphone is not recording.")
                stream = self._stream
                self._stream = None
                self._recording = False
            stop_error: Exception | None = None
            try:
                stream.stop()
            except Exception as error:
                stop_error = error
            try:
                stream.close()
            except Exception as error:
                if stop_error is None:
                    stop_error = error
            with self._lock:
                chunks, self._chunks = self._chunks, []
                sample_rate = self._sample_rate
                overflow = self._overflow
                capture_error = self._capture_error
            if capture_error is not None:
                raise RuntimeError("Microphone capture failed.") from capture_error
            if stop_error is not None:
                raise RuntimeError("Microphone could not be stopped cleanly.") from stop_error
            samples = np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)
            return CapturedAudio(samples=samples, sample_rate=sample_rate, overflow=overflow)

    def close(self) -> None:
        with self._lifecycle_lock:
            with self._lock:
                stream = self._stream
                self._stream = None
                self._recording = False
                self._chunks = []
                self._sample_count = 0
                self._overflow = False
                self._limit_reached = False
                self._capture_error = None
            if stream is not None:
                try:
                    stream.abort()
                finally:
                    stream.close()


def to_16khz(captured: CapturedAudio) -> np.ndarray:
    """Resample once with soxr HQ and return contiguous mono float32 audio."""
    samples = _mono(captured.samples)
    sample_rate = _rate(captured.sample_rate)
    if not len(samples) or sample_rate == 16000:
        return np.ascontiguousarray(samples)
    soxr = importlib.import_module("soxr")
    return np.ascontiguousarray(
        soxr.resample(samples, sample_rate, 16000, quality="HQ"), dtype=np.float32
    )


def is_silent(samples: np.ndarray, threshold: float = 0.001) -> bool:
    """Conservative short-window RMS gate for 16 kHz audio, not speech detection.

    Inspect overlapping 100 ms windows so long silences do not dilute a brief
    phrase. The default threshold is about -60 dBFS. Empty recordings are silent.
    Quiet speech may require a smaller threshold; background noise can pass this
    gate and is left for the recognizer to handle.
    """
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("Silence threshold must be finite and nonnegative.")
    audio = _mono(samples)
    if not len(audio):
        return True
    window_samples = 1600
    for start in range(0, len(audio), window_samples // 2):
        window = audio[start : start + window_samples]
        # Squaring one small window avoids a large float64 temporary for long clips.
        rms = np.sqrt(np.mean(np.square(window, dtype=np.float64)))
        if not rms <= threshold:
            return False
    return True


def split_audio(
    samples: np.ndarray,
    sample_rate: int = 16000,
    max_seconds: float = 28.0,
    min_seconds: float = 8.0,
) -> list[np.ndarray]:
    """Split at low-energy boundaries with exact coverage and no overlap.

    For each full chunk, inspect 200 ms windows at 20 ms intervals in its last
    three seconds. Choose the lowest-energy midpoint, preferring the latest tie.
    Every sample appears exactly once, including a short final tail. This is a
    clip segmentation heuristic; it does not promise complete sentence breaks.
    """
    audio = _mono(samples)
    rate = _rate(sample_rate)
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("max_seconds must be finite and positive.")
    if not math.isfinite(min_seconds) or not 0 < min_seconds <= max_seconds:
        raise ValueError("min_seconds must be positive and at most max_seconds.")
    max_samples = int(max_seconds * rate)
    min_samples = max(1, int(min_seconds * rate))
    if max_samples < 1:
        raise ValueError("max_seconds must allow at least one audio sample.")
    result: list[np.ndarray] = []
    start = 0
    half_window = max(1, int(0.1 * rate))
    step = max(1, int(0.02 * rate))
    while len(audio) - start > max_samples:
        end = start + max_samples
        search_start = max(start + min_samples, end - int(3 * rate))
        candidates = np.arange(search_start, end, step, dtype=np.int64)
        candidates = np.append(candidates, end)
        window_start = np.maximum(candidates - half_window, start)
        window_end = np.minimum(candidates + half_window, len(audio))
        region_start = int(window_start[0])
        region_end = int(window_end[-1])
        energy = np.concatenate(
            ([0.0], np.cumsum(np.square(audio[region_start:region_end], dtype=np.float64)))
        )
        means = (
            energy[window_end - region_start] - energy[window_start - region_start]
        ) / (window_end - window_start)
        # Reverse argmin makes constant-energy regions use the latest boundary.
        choice = len(means) - 1 - int(np.argmin(means[::-1]))
        boundary = int(candidates[choice])
        result.append(audio[start:boundary])
        start = boundary
    if start < len(audio):
        result.append(audio[start:])
    return result
