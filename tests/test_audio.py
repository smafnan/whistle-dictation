"""Microphone contract tests use a fake PortAudio stream, never real hardware."""

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from whistle_dictation import audio as audio_module
from whistle_dictation.audio import (
    CapturedAudio,
    MicrophoneRecorder,
    input_devices,
    is_silent,
    split_audio,
    to_16khz,
)


@pytest.fixture
def microphone(monkeypatch):
    streams = []

    class FakeStream:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            self.started = False
            self.aborted = False
            streams.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.started = False

        def close(self):
            self.closed = True

        def abort(self):
            self.aborted = True
            self.started = False

        def feed(self, samples, *, overflow=False):
            data = np.asarray(samples, dtype=np.float32).reshape(-1, 1)
            self.kwargs["callback"](
                data, len(data), None, SimpleNamespace(input_overflow=overflow)
            )
            return data

    devices = [
        {"name": "Speaker", "max_input_channels": 0, "default_samplerate": 48000},
        {"name": "Microphone", "max_input_channels": 1, "default_samplerate": 1000},
    ]

    def query_devices(device=None, kind=None):
        return devices if kind is None else devices[1 if device is None else device]

    api = SimpleNamespace(InputStream=FakeStream, query_devices=query_devices)
    monkeypatch.setitem(sys.modules, "sounddevice", api)
    return streams


def test_capture_caps_memory_copies_callback_and_reports_overflow(microphone):
    recorder = MicrophoneRecorder(max_seconds=1)
    recorder.start()
    stream = microphone[-1]
    source = stream.feed(np.full(700, 0.25))
    source[:] = 0.75  # PortAudio's reused buffer cannot change captured audio.
    stream.feed(np.full(700, 0.5), overflow=True)
    stream.feed(np.full(5000, 0.9))
    assert recorder.limit_reached
    assert recorder.elapsed == 1.0
    captured = recorder.stop()
    assert stream.closed
    assert captured.sample_rate == 1000
    assert captured.samples.dtype == np.float32
    assert len(captured.samples) == 1000
    assert captured.overflow
    assert captured.duration == 1.0
    np.testing.assert_array_equal(captured.samples[:700], np.full(700, 0.25))
    np.testing.assert_array_equal(captured.samples[700:], np.full(300, 0.5))


def test_empty_capture_and_restart_reset_state(microphone):
    recorder = MicrophoneRecorder(max_seconds=1)
    recorder.start()
    first = recorder.stop()
    assert first.samples.size == 0
    assert first.duration == 0
    recorder.start()
    microphone[-1].feed([0.1, 0.2], overflow=True)
    recorder.stop()
    recorder.start()
    assert recorder.elapsed == 0
    assert not recorder.limit_reached
    assert not recorder.stop().overflow


def test_absolute_sample_budget_caps_capture_before_time_limit(microphone, monkeypatch):
    monkeypatch.setattr(audio_module, "MAX_CAPTURE_SAMPLES", 2500)
    recorder = MicrophoneRecorder(max_seconds=300)
    recorder.start()
    microphone[-1].feed(np.full(10000, 0.25))
    assert recorder.limit_reached
    assert recorder.elapsed == 2.5
    captured = recorder.stop()
    assert captured.duration == 2.5
    assert len(captured.samples) == 2500


def test_close_discards_audio_and_late_callbacks(microphone):
    recorder = MicrophoneRecorder()
    recorder.start()
    stream = microphone[-1]
    stream.feed([0.2, 0.3])
    recorder.close()
    stream.feed([0.2, 0.3])
    recorder.close()
    assert recorder.elapsed == 0
    assert stream.aborted and stream.closed
    with pytest.raises(RuntimeError, match="not recording"):
        recorder.stop()


def test_start_failure_closes_stream_and_allows_retry(microphone, monkeypatch):
    recorder = MicrophoneRecorder()
    api = sys.modules["sounddevice"]
    original = api.InputStream

    def failed_stream(**kwargs):
        stream = original(**kwargs)

        def fail():
            raise RuntimeError("Device disconnected")

        stream.start = fail
        return stream

    monkeypatch.setattr(api, "InputStream", failed_stream)
    with pytest.raises(RuntimeError, match="disconnected"):
        recorder.start()
    assert microphone[-1].closed
    monkeypatch.setattr(api, "InputStream", original)
    recorder.start()
    recorder.close()


def test_stop_failure_still_closes_and_releases_captured_buffers(microphone):
    recorder = MicrophoneRecorder()
    recorder.start()
    stream = microphone[-1]
    stream.feed([0.2, 0.3])

    def fail():
        raise RuntimeError("Device disappeared")

    stream.stop = fail
    with pytest.raises(RuntimeError, match="stopped cleanly"):
        recorder.stop()
    assert stream.closed
    assert recorder._chunks == []
    recorder.start()
    recorder.close()


def test_callback_failure_is_reported_after_device_cleanup(microphone):
    recorder = MicrophoneRecorder()
    recorder.start()
    stream = microphone[-1]
    stream.kwargs["callback"](
        np.ones(10, dtype=np.float32), 10, None, SimpleNamespace(input_overflow=False)
    )
    assert recorder.limit_reached
    with pytest.raises(RuntimeError, match="capture failed"):
        recorder.stop()
    assert stream.closed


def test_device_listing_preserves_native_device_indices(microphone):
    assert input_devices() == [{"index": 1, "name": "Microphone", "sample_rate": 1000}]


@pytest.mark.parametrize("limit", [0, -1, 3601, 1.5, True])
def test_invalid_capture_limit(limit):
    with pytest.raises(ValueError):
        MicrophoneRecorder(max_seconds=limit)


def test_split_prefers_silence_near_clip_limit():
    samples = np.full(61000, 0.5, dtype=np.float32)
    samples[26000:26800] = 0
    chunks = split_audio(samples, sample_rate=1000)
    assert 26000 < len(chunks[0]) < 26800
    assert all(len(chunk) <= 28000 for chunk in chunks)
    np.testing.assert_array_equal(np.concatenate(chunks), samples)


@pytest.mark.parametrize("length", [1, 28000, 28001, 56000, 120123])
def test_split_covers_every_sample_once_including_short_tail(length):
    samples = np.random.default_rng(7).uniform(-0.5, 0.5, length).astype(np.float32)
    chunks = split_audio(samples, sample_rate=1000)
    assert chunks
    assert all(0 < len(chunk) <= 28000 for chunk in chunks)
    assert all(len(chunk) >= 8000 for chunk in chunks[:-1])
    np.testing.assert_array_equal(np.concatenate(chunks), samples)


def test_constant_energy_uses_full_chunks():
    samples = np.full(56003, 0.25, dtype=np.float32)
    chunks = split_audio(samples, sample_rate=1000)
    assert [len(chunk) for chunk in chunks] == [28000, 28000, 3]


def test_empty_and_silence_gate():
    assert split_audio(np.empty(0, dtype=np.float32)) == []
    assert is_silent(np.empty(0, dtype=np.float32))
    assert is_silent(np.zeros(1000, dtype=np.float32))
    assert is_silent(np.full(1000, 0.0001, dtype=np.float32))
    assert not is_silent(np.full(1000, 0.01, dtype=np.float32))


def test_silence_gate_preserves_brief_quiet_phrase_in_long_recording():
    samples = np.zeros(320000, dtype=np.float32)
    samples[160001:164001] = 0.002
    assert not is_silent(samples)


def test_silence_gate_accepts_long_recording_with_only_quiet_background():
    samples = np.full(320000, 0.0001, dtype=np.float32)
    assert is_silent(samples)


def test_resample_native_rate_needs_no_resampler():
    samples = np.ones(200, dtype=np.float32)
    output = to_16khz(CapturedAudio(samples, 16000))
    assert output.dtype == np.float32
    assert output.flags.c_contiguous
    np.testing.assert_array_equal(output, samples)


def test_resample_shape_dtype_and_tone_frequency():
    # Real soxr verifies duration and waveform, not just a mocked API call.
    sample_rate = 48000
    samples = np.sin(2 * np.pi * 440 * np.arange(sample_rate) / sample_rate).astype(np.float32)
    output = to_16khz(CapturedAudio(samples, sample_rate))
    assert output.shape == (16000,)
    assert output.dtype == np.float32
    assert output.flags.c_contiguous
    peak_hz = np.argmax(np.abs(np.fft.rfft(output)))
    assert peak_hz == 440
    assert is_silent(output) is False
