from dataclasses import asdict
import hashlib
import io
import json
import pickle
import queue
import sys
import threading
import time
from types import SimpleNamespace
import wave

import numpy as np
import pytest

from whistle_dictation import engine, runtime
from whistle_dictation.audio import CapturedAudio
from whistle_dictation.config import Settings


class FakeModel:
    def __init__(self, responses=None):
        self.responses = iter(responses if responses is not None else [{"text": "hello"}])
        self.calls = []

    def transcribe(self, samples, **options):
        self.calls.append((samples.copy(), options))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def captured(seconds=1):
    samples = np.full(int(seconds * 16000), 0.1, dtype=np.float32)
    return CapturedAudio(samples, 16000)


def test_recording_chunks_cover_audio_and_forward_language_dictionary_progress():
    recording = captured(60)
    recording.samples[:] += np.arange(len(recording.samples), dtype=np.float32) * 1e-8
    model = FakeModel([{"text": "first"}, {"text": "second"}, {"text": "third"}])
    progress = []
    settings = Settings(language="de", keywords=["München", "Cactus Needle"])
    result = engine.transcribe_recording(model, recording, settings,
                                         lambda current, total: progress.append((current, total)))
    assert result["text"] == "First second third"
    assert result["chunks"] == 3
    assert result["seconds"] >= 0
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert all(0 < len(samples) <= 28 * 16000 for samples, _ in model.calls)
    np.testing.assert_array_equal(np.concatenate([samples for samples, _ in model.calls]),
                                  recording.samples)
    assert all(options == {"language": "de", "keywords": settings.keywords}
               for _, options in model.calls)


def test_silent_recording_skips_engine_and_progress():
    model = FakeModel()
    progress = []
    recording = CapturedAudio(np.zeros(16000, dtype=np.float32), 16000)
    result = engine.transcribe_recording(model, recording, Settings(),
                                         lambda *args: progress.append(args))
    assert result["text"] == "" and result["chunks"] == 0
    assert model.calls == [] and progress == []


@pytest.mark.parametrize("response", [None, "text", {}, {"text": None}, {"text": 3}])
def test_invalid_model_output_cannot_be_delivered(response):
    with pytest.raises(RuntimeError, match="invalid transcript"):
        engine.transcribe_recording(FakeModel([response]), captured(), Settings())


def test_model_errors_propagate_without_partial_transcript():
    model = FakeModel([{"text": "first"}, RuntimeError("native decoder failed")])
    with pytest.raises(RuntimeError, match="native decoder failed"):
        engine.transcribe_recording(model, captured(35), Settings())


class FakeQueue(queue.Queue):
    def __init__(self, maxsize=0):
        super().__init__(maxsize)
        self.closed = False
        self.join_cancelled = False

    def cancel_join_thread(self):
        self.join_cancelled = True

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.alive = False
        self.closed = False
        self.terminated = False
        self.killed = False

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.terminated = True
        self.alive = False

    def join(self, timeout=None):
        pass

    def kill(self):
        self.killed = True
        self.alive = False

    def close(self):
        self.closed = True


class FakeContext:
    def Queue(self, maxsize=0):
        return FakeQueue(maxsize)

    def Process(self, **kwargs):
        return FakeProcess(**kwargs)


@pytest.fixture
def service(tmp_path, monkeypatch):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(engine.mp, "get_context", lambda method: FakeContext())
    monkeypatch.setattr(engine.time, "monotonic", lambda: clock.now)
    instance = engine.EngineService(tmp_path)
    instance.start()
    yield instance, clock
    instance.close()


def make_ready(service):
    service._responses.put({"kind": "ready"})
    assert service.poll() == [{"kind": "ready"}]
    assert service.ready


def assert_memory_gone(name):
    try:
        attachment = engine.shared_memory.SharedMemory(name=name)
    except FileNotFoundError:
        return
    attachment.close()
    pytest.fail("Audio shared memory remained allocated after the request ended")


def test_service_single_flight_and_result_releases_busy_state(service):
    instance, _ = service
    with pytest.raises(RuntimeError, match="not ready"):
        instance.submit("a", captured(), Settings())
    make_ready(instance)
    settings = Settings(language=None, keywords=["Needle"])
    instance.submit("a", captured(), settings)
    task = instance._requests.get_nowait()
    assert task["request_id"] == "a" and task["sample_rate"] == 16000
    assert task["settings"] == asdict(settings)
    assert "samples" not in task
    assert task["sample_count"] == 16000
    assert len(pickle.dumps(task)) < 2048
    attachment = engine.shared_memory.SharedMemory(name=task["audio_name"])
    view = np.ndarray((16000,), dtype=np.float32, buffer=attachment.buf)
    np.testing.assert_array_equal(view, captured().samples)
    del view
    attachment.close()
    with pytest.raises(RuntimeError, match="busy"):
        instance.submit("b", captured(), settings)
    instance._responses.put({"kind": "progress", "request_id": "a", "current": 1, "total": 1})
    assert instance.poll()[0]["kind"] == "progress"
    with pytest.raises(RuntimeError, match="busy"):
        instance.submit("b", captured(), settings)
    instance._responses.put({"kind": "result", "request_id": "a", "text": "hello"})
    assert instance.poll()[0]["text"] == "hello"
    assert instance._audio_memory is None
    assert_memory_gone(task["audio_name"])
    instance.submit("b", captured(), settings)


@pytest.mark.parametrize("during_inference", [False, True])
def test_timeout_stops_worker_and_returns_request_identity(service, during_inference):
    instance, clock = service
    process, requests, responses = instance._process, instance._requests, instance._responses
    if during_inference:
        make_ready(instance)
        instance.submit("timed-out", captured(), Settings(inference_timeout_seconds=15))
        memory_name = instance._audio_memory.name
        clock.now += 16
    else:
        clock.now += 91
    messages = instance.poll()
    assert len(messages) == 1 and messages[0]["kind"] == "error"
    assert "timed out" in messages[0]["message"]
    assert messages[0]["request_id"] == ("timed-out" if during_inference else None)
    assert process.terminated and process.closed
    assert requests.closed and responses.closed
    assert not instance.ready and instance._process is None
    assert instance.poll() == []
    if during_inference:
        assert_memory_gone(memory_name)


def test_crashed_worker_is_reported_and_cleaned_up(service):
    instance, _ = service
    make_ready(instance)
    instance.submit("crashed", captured(), Settings())
    memory_name = instance._audio_memory.name
    process = instance._process
    process.alive = False
    messages = instance.poll()
    assert messages[0]["kind"] == "error" and messages[0]["request_id"] == "crashed"
    assert "stopped unexpectedly" in messages[0]["message"]
    assert process.closed and instance._process is None
    assert_memory_gone(memory_name)


@pytest.mark.parametrize("kind", ["result", "error"])
def test_matching_terminal_response_releases_audio_mapping(service, kind):
    instance, _ = service
    make_ready(instance)
    instance.submit("finished", captured(), Settings())
    memory_name = instance._audio_memory.name
    instance._responses.put({"kind": kind, "request_id": "finished"})
    assert instance.poll()[0]["kind"] == kind
    assert instance._pending is None and instance._audio_memory is None
    assert_memory_gone(memory_name)


def test_stale_terminal_response_cannot_release_current_audio_mapping(service):
    instance, _ = service
    make_ready(instance)
    instance.submit("current", captured(), Settings())
    memory = instance._audio_memory
    instance._responses.put({"kind": "result", "request_id": "previous"})
    instance.poll()
    assert instance._pending == "current" and instance._audio_memory is memory


def test_immediate_cancel_releases_large_mapping(service):
    instance, _ = service
    make_ready(instance)
    audio = CapturedAudio(np.full(8_000_000, 0.1, dtype=np.float32), 48000)
    instance.submit("cancel", audio, Settings())
    memory_name = instance._audio_memory.name
    task = instance._requests.get_nowait()
    assert len(pickle.dumps(task)) < 2048
    instance.close()
    assert instance._audio_memory is None
    assert_memory_gone(memory_name)


def test_submit_queue_failure_releases_allocated_mapping(service, monkeypatch):
    instance, _ = service
    make_ready(instance)
    allocations = []
    original = engine.shared_memory.SharedMemory

    def allocate(*args, **kwargs):
        memory = original(*args, **kwargs)
        allocations.append(memory.name)
        return memory

    def full(_):
        raise queue.Full

    monkeypatch.setattr(engine.shared_memory, "SharedMemory", allocate)
    monkeypatch.setattr(instance._requests, "put_nowait", full)
    with pytest.raises(queue.Full):
        instance.submit("failed-to-submit", captured(), Settings())
    assert instance._audio_memory is None and instance._pending is None
    assert len(allocations) == 1
    assert_memory_gone(allocations[0])


@pytest.mark.parametrize("samples", [np.empty(0, dtype=np.float32), np.zeros((2, 2)),
                                      np.array([np.nan]), np.array([np.inf])])
def test_invalid_audio_is_rejected_without_allocating_memory(service, samples):
    instance, _ = service
    make_ready(instance)
    with pytest.raises(RuntimeError):
        instance.submit("invalid", CapturedAudio(samples, 16000), Settings())
    assert instance._audio_memory is None and instance._pending is None


def test_audio_transport_cap_is_checked_before_allocating_memory(service, monkeypatch):
    instance, _ = service
    make_ready(instance)
    monkeypatch.setattr(engine, "MAX_AUDIO_BYTES", 64)
    with pytest.raises(RuntimeError, match="audio transport limit"):
        instance.submit("oversized", captured(), Settings())
    assert instance._audio_memory is None


def test_handled_startup_error_does_not_add_generic_crash_error(service):
    instance, _ = service
    instance._responses.put({"kind": "error", "request_id": None, "message": "bad weights"})
    instance._process.alive = False
    assert instance.poll() == [{"kind": "error", "request_id": None, "message": "bad weights"}]
    assert instance._process is None


def test_close_kills_stubborn_worker_and_releases_queues(service, monkeypatch):
    instance, _ = service
    process, requests, responses = instance._process, instance._requests, instance._responses
    monkeypatch.setattr(process, "terminate", lambda: None)
    instance.close()
    instance.close()
    assert process.killed and process.closed
    assert requests.join_cancelled and requests.closed
    assert responses.join_cancelled and responses.closed
    assert instance._pending is None and instance._deadline == 0


def test_queue_reader_closes_before_feeder_sentinel_with_bounded_join(service):
    instance, _ = service
    events = []
    connection = instance._requests
    connection._reader = SimpleNamespace(close=lambda: events.append("reader"))
    connection._writer = SimpleNamespace(close=lambda: events.append("writer"))
    connection._thread = SimpleNamespace(
        join=lambda timeout: events.append(("join", timeout)), is_alive=lambda: False,
    )
    original_close = connection.close

    def close():
        events.append("sentinel")
        original_close()

    connection.close = close
    instance.close()
    assert events == ["reader", "sentinel", ("join", 0.5), "writer"]


def test_worker_initialization_failure_returns_useful_error(tmp_path, monkeypatch):
    def fail(_):
        raise RuntimeError("checksum mismatch")

    monkeypatch.setattr(engine, "configure_environment", lambda _: None)
    monkeypatch.setattr(engine, "verify_runtime", fail)
    requests, responses = FakeQueue(), FakeQueue()
    engine.worker_main(str(tmp_path), requests, responses)
    assert responses.get_nowait() == {
        "kind": "error", "request_id": None, "message": "checksum mismatch",
    }
    assert responses.empty()


def test_worker_recovers_from_request_error_and_keeps_request_ids(tmp_path, monkeypatch):
    model = FakeModel([RuntimeError("bad clip"), {"text": "second clip"}])
    monkeypatch.setattr(engine, "configure_environment", lambda _: None)
    monkeypatch.setattr(engine, "verify_runtime", lambda _: {})
    monkeypatch.setitem(sys.modules, "needle", SimpleNamespace(Whistle=lambda weights: model))
    requests, responses = FakeQueue(), FakeQueue()
    recording = captured()
    owner = engine.shared_memory.SharedMemory(create=True, size=recording.samples.nbytes)
    view = np.ndarray(recording.samples.shape, dtype=np.float32, buffer=owner.buf)
    view[:] = recording.samples
    del view
    attached = []
    original = engine.shared_memory.SharedMemory

    def attach(*args, **kwargs):
        memory = original(*args, **kwargs)
        attached.append(memory)
        return memory

    monkeypatch.setattr(engine.shared_memory, "SharedMemory", attach)
    try:
        for request_id in ("failed", "successful"):
            requests.put({
                "request_id": request_id, "audio_name": owner.name,
                "sample_count": len(recording.samples), "sample_rate": 16000,
                "overflow": False, "settings": asdict(Settings()),
            })
        requests.put(None)
        engine.worker_main(str(tmp_path), requests, responses)
        assert len(attached) == 2 and all(memory.buf is None for memory in attached)
        # Worker closes its attachments and leaves parent ownership intact.
        remaining = original(name=owner.name)
        remaining.close()
    finally:
        owner.close()
        owner.unlink()
    messages = []
    while not responses.empty():
        messages.append(responses.get_nowait())
    assert messages[0] == {"kind": "ready"}
    assert messages[1] == {"kind": "error", "request_id": "failed", "message": "bad clip"}
    assert messages[2] == {
        "kind": "progress", "request_id": "successful", "current": 1, "total": 1,
    }
    assert messages[3]["kind"] == "result" and messages[3]["request_id"] == "successful"
    assert messages[3]["text"] == "Second clip"


def test_download_integrity_failure_preserves_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "model.cact"
    target.write_bytes(b"previous valid model")
    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"broken"))
    with pytest.raises(RuntimeError, match="Integrity check failed"):
        runtime._download("https://example.invalid/model", target, "0" * 64)
    assert target.read_bytes() == b"previous valid model"
    assert not target.with_suffix(".cact.partial").exists()


def test_download_verified_cache_needs_no_network(tmp_path, monkeypatch):
    target = tmp_path / "runtime.whl"
    target.write_bytes(b"verified artifact")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()

    def unavailable(*_, **__):
        pytest.fail("Verified artifact should not need a network request")

    monkeypatch.setattr(runtime.urllib.request, "urlopen", unavailable)
    runtime._download("https://example.invalid/runtime", target, expected)


def test_download_verified_bytes_replace_corrupt_cache(tmp_path, monkeypatch):
    target = tmp_path / "runtime.whl"
    target.write_bytes(b"corrupt cache")
    correct = b"verified runtime"
    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(correct))
    runtime._download("https://example.invalid/runtime", target, hashlib.sha256(correct).hexdigest())
    assert target.read_bytes() == correct
    assert not target.with_suffix(".whl.partial").exists()


def test_runtime_verification_reports_corrupt_model(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    (models / "whistle.cact").write_bytes(b"tampered")
    (models / "libneedle.dll").write_bytes(b"library")
    (models / "manifest.json").write_text(json.dumps({
        "architecture": "win_amd64",
        "library_sha256": hashlib.sha256(b"library").hexdigest(),
    }), encoding="utf-8")
    monkeypatch.setattr(runtime.platform, "machine", lambda: "AMD64")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        runtime.verify_runtime(tmp_path)


def write_runtime_fixture(root, library_bytes, architecture="win_amd64"):
    models = root / "models"
    models.mkdir()
    weights = b"fixture model"
    (models / "whistle.cact").write_bytes(weights)
    (models / "libneedle.dll").write_bytes(library_bytes)
    manifest = {
        "package": "cactus-needle==3.1.0", "architecture": architecture,
        "engine_revision": runtime.ENGINE_REVISION, "model_revision": runtime.MODEL_REVISION,
        "model_sha256": hashlib.sha256(weights).hexdigest(),
        "library_sha256": hashlib.sha256(library_bytes).hexdigest(),
        "wheel_sha256": runtime.WHEELS["ARM64" if architecture == "win_arm64" else "AMD64"][1],
    }
    (models / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


@pytest.mark.parametrize("machine,tag", [("AMD64", "win_amd64"), ("ARM64", "win_arm64")])
def test_runtime_rejects_tampered_dll_even_when_manifest_forges_matching_hash(
        tmp_path, monkeypatch, machine, tag):
    manifest = write_runtime_fixture(tmp_path, b"tampered publisher DLL", tag)
    monkeypatch.setattr(runtime, "MODEL_SHA256", manifest["model_sha256"])
    monkeypatch.setattr(runtime.platform, "machine", lambda: machine)
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        runtime.verify_runtime(tmp_path)


@pytest.mark.parametrize("machine,tag", [("AMD64", "win_amd64"), ("ARM64", "win_arm64")])
def test_runtime_accepts_both_architectures_only_when_frozen_hashes_match(
        tmp_path, monkeypatch, machine, tag):
    manifest = write_runtime_fixture(tmp_path, b"verified publisher DLL", tag)
    monkeypatch.setattr(runtime, "MODEL_SHA256", manifest["model_sha256"])
    monkeypatch.setitem(runtime.LIBRARY_SHA256, machine, manifest["library_sha256"])
    monkeypatch.setattr(runtime.platform, "machine", lambda: machine)
    assert runtime.verify_runtime(tmp_path) == manifest


@pytest.mark.parametrize("contents", ["[]", "null", '"unexpected text"'])
def test_nonobject_runtime_manifest_reports_repair_action(tmp_path, monkeypatch, contents):
    manifest = write_runtime_fixture(tmp_path, b"verified publisher DLL")
    monkeypatch.setattr(runtime, "MODEL_SHA256", manifest["model_sha256"])
    monkeypatch.setitem(runtime.LIBRARY_SHA256, "AMD64", manifest["library_sha256"])
    monkeypatch.setattr(runtime.platform, "machine", lambda: "AMD64")
    models = tmp_path / "models"
    (models / "manifest.json").write_text(contents, encoding="utf-8")
    with pytest.raises(RuntimeError, match="Setup.ps1"):
        runtime.verify_runtime(tmp_path)


def test_runtime_configuration_disables_network_and_uses_local_paths(tmp_path, monkeypatch):
    names = ("NEEDLE_TELEMETRY", "DO_NOT_TRACK", "HF_HUB_DISABLE_TELEMETRY", "HF_HUB_OFFLINE",
             "NEEDLE3_LIB_PATH", "NEEDLE_WHISTLE_WEIGHTS")
    for name in names:
        monkeypatch.setenv(name, "previous")
    runtime.configure_environment(tmp_path)
    assert runtime.os.environ["NEEDLE_TELEMETRY"] == "0"
    assert all(runtime.os.environ[name] == "1" for name in names[1:4])
    assert runtime.os.environ["NEEDLE3_LIB_PATH"] == str(tmp_path / "models" / "libneedle.dll")
    assert runtime.os.environ["NEEDLE_WHISTLE_WEIGHTS"] == str(tmp_path / "models" / "whistle.cact")


def wait_for_engine(instance, kind, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for message in instance.poll():
            if message["kind"] == "error":
                pytest.fail(message["message"])
            if message["kind"] == kind:
                return message
        time.sleep(0.01)
    pytest.fail(f"Worker did not send {kind} within {timeout} seconds")


def real_runtime_root():
    root = runtime.app_directory()
    if sys.platform != "win32" or not (root / "models" / "manifest.json").is_file():
        pytest.skip("Downloaded Windows Whistle runtime is required")
    return root


@pytest.mark.integration
def test_real_worker_transcribes_generated_speech_through_shared_memory():
    root = real_runtime_root()
    path = root / ".cache" / "speech-smoke.wav"
    if not path.is_file():
        pytest.skip("Generated speech smoke fixture is required")
    with wave.open(str(path), "rb") as source:
        assert source.getnchannels() == 1 and source.getsampwidth() == 2
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32)
        recording = CapturedAudio(audio / 32768.0, source.getframerate())
    instance = engine.EngineService(root)
    try:
        instance.start()
        wait_for_engine(instance, "ready")
        instance.submit("generated-speech", recording, Settings())
        memory_name = instance._audio_memory.name
        message = wait_for_engine(instance, "result")
        assert message["request_id"] == "generated-speech"
        assert "dictation" in message["text"].casefold()
        assert instance._audio_memory is None
        assert_memory_gone(memory_name)
    finally:
        instance.close()


@pytest.mark.integration
@pytest.mark.parametrize("maximal_settings", [False, True])
def test_real_immediate_cancel_leaves_no_shared_mapping_or_queue_feeder(maximal_settings):
    root = real_runtime_root()
    initial_threads = set(threading.enumerate())
    settings = Settings()
    if maximal_settings:
        settings = Settings(
            keywords=[f"{index:03d}" + "K" * 117 for index in range(128)],
            replacements={f"{index:03d}" + "R" * 117: f"{index:03d}" + "V" * 497
                          for index in range(128)},
        ).validate()
        assert len(pickle.dumps(asdict(settings))) > 64 * 1024
    instance = engine.EngineService(root)
    try:
        instance.start()
        wait_for_engine(instance, "ready")
        recording = CapturedAudio(np.full(8_000_000, 0.1, dtype=np.float32), 48000)
        instance.submit("cancel-immediately", recording, settings)
        memory_name = instance._audio_memory.name
    finally:
        instance.close()
    assert_memory_gone(memory_name)
    time.sleep(0.5)
    assert [thread for thread in threading.enumerate()
            if thread.name == "QueueFeederThread" and thread not in initial_threads] == []
