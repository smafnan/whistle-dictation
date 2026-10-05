"""Native recognition/segmentation check on synthetic speech; no microphone or insertion."""
from __future__ import annotations

import json
from pathlib import Path
import re
import time
import wave

import numpy as np

from whistle_dictation.audio import CapturedAudio
from whistle_dictation.config import Settings
from whistle_dictation.engine import transcribe_recording
from whistle_dictation.runtime import configure_environment, verify_runtime


def word_error_rate(reference: str, hypothesis: str) -> float:
    expected = re.findall(r"\w+", reference.casefold())
    actual = re.findall(r"\w+", hypothesis.casefold())
    previous = list(range(len(actual) + 1))
    for row, left in enumerate(expected, 1):
        current = [row]
        for column, right in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (left != right)))
        previous = current
    return previous[-1] / max(1, len(expected))


def main():
    root = Path(__file__).resolve().parents[1]
    configure_environment(root)
    verify_runtime(root)
    import needle

    path = root / ".cache" / "speech-long.wav"
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2 or source.getnchannels() != 1:
            raise RuntimeError("Synthetic verification expects mono 16-bit PCM.")
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768
        captured = CapturedAudio(audio, source.getframerate())
    started = time.perf_counter()
    model = needle.Whistle(weights=str(root / "models" / "whistle.cact"))
    load_seconds = time.perf_counter() - started
    reference = (root / "tests" / "fixtures" / "synthetic-reference.txt").read_text(encoding="utf-8").strip()
    result = transcribe_recording(model, captured, Settings())
    report = {"kind": "generated_speech", "audio_seconds": captured.duration,
              "sample_rate": captured.sample_rate, "model_load_seconds": load_seconds,
              **result, "word_error_rate": word_error_rate(reference, result["text"]),
              "normalization": "casefold; Unicode word tokens; punctuation ignored"}
    target = root / ".cache" / "speech-validation.json"
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if captured.duration <= 30 or result["chunks"] < 2:
        raise RuntimeError("Generated clip was too short to verify multi-segment decoding.")
    if report["word_error_rate"] > 0.10:
        raise RuntimeError("Synthetic speech exceeded this smoke check's 10% WER threshold.")


if __name__ == "__main__":
    main()
