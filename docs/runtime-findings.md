# Whistle runtime findings

Verified on 5 October 2026 against the public publisher repositories, PyPI metadata, and the actual pinned Windows wheel bytes. These findings establish the integration contract; they do not establish accuracy or microphone performance on this computer.

## Python API

Pin `cactus-needle==3.1.0` for this implementation. The released PyPI wheel was inspected without executing it and matches this API:

```python
model = needle.Whistle(weights="models/whistle.cact", buffer_size=1 << 18)
result = model.transcribe(
    audio,
    language="en",
    keywords=["product name", "technical phrase"],
    word_timestamps=False,
)
```

Supply a WAV path or a **one-dimensional sequence of mono float samples at 16,000 Hz**, scaled to `[-1, 1]`. At most 480,000 samples fit in a pass. The native engine rejects longer audio, so segmentation belongs in the application. Allow a margin below 30 seconds.

Supported language codes: `en`, `de`, `fr`, `es`, `it`, `nl`, `pl`. `None` requests detection. The result includes `text`, `language`, `ttft_ms`, and `decode_tps`; timestamps add `words` entries with `word`, `start`, `end`, and `probability`. Silence can produce empty text and language.

The wrapper joins keyword phrases with newlines; it documents no numeric keyword limit. Application limits are resource controls, not claimed model limits. There is no documented incremental streaming method.

The runtime has process-global model state and is explicitly **not thread-safe**. Keep initialization and transcription on one serialized worker process. Do not mix another Needle model in that process.

Sources: [published API implementation](https://github.com/cactus-compute/needle/blob/main/needle/agent/whistle.py), [native-limit and response tests](https://github.com/cactus-compute/needle/blob/main/tests/test_whistle.py), [release architecture](https://cactuscompute.com/blog/whistle).

## Windows artifacts and reproducibility

The pinned AMD64 wheel was inspected in memory: `needle/libneedle3.dll` has PE machine `0x8664` (AMD64), and exports `needle_transcribe`, `needle_load`, and `needle_last_error`. ARM64 is a separate artifact. This resolves the release article's incomplete Windows platform summary; it does not replace a local model-load/transcription check.

| Artifact | Immutable repository revision | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `whistle.cact` | `Cactus-Compute/whistle` at `b358ddadd89b7a713b5aa131f23032d3cca1b251` | 16,919,407 | `b6e02f048568ac5d01a2042556c658061e699acbc0aa2a1439f52f3d461dffeb` |
| `python/cactus_needle-3.1.0-py3-none-win_amd64.whl` | `Cactus-Compute/needle3` at `c7c415a3d1b3d929014bc6e866d51ebb971f7089` | 683,889 | `4f5fc86abfc50d551cdb237a34b501f36d82d4b6f5911ee7bec4e9532d44dd95` |
| `python/cactus_needle-3.1.0-py3-none-win_arm64.whl` | `Cactus-Compute/needle3` at `c7c415a3d1b3d929014bc6e866d51ebb971f7089` | 617,795 | `39806d54910c207cd0ac5dc60009c8c5330072ef729711d74061faf0e99e7a6c` |
| PyPI `cactus_needle-3.1.0-py3-none-any.whl` | PyPI release `3.1.0` | 106,372 | `4101e693757d969782ce1d0d6aac9756bfca80a163a26f13c39e5c5aacecea68` |

The extracted `needle/libneedle3.dll` also has a frozen hash, independent of the editable installation manifest:

| Architecture | DLL SHA-256 | PE machine |
| --- | --- | --- |
| AMD64 | `de2e2c39cd311fbd9971fad4736abc329ed970653674c203e149c4ef27fd1c62` | `0x8664` |
| ARM64 | `a4b13bfde65a188982c309b52133ab4ad7d0e63a9b46ba55c3b76a1d32927f7a` | `0xaa64` |

The ARM64 DLL is 1,298,432 bytes. Both hashes were obtained from the pinned wheel's actual contents. Compare the installed DLL with these constants on startup; a manifest-provided hash alone cannot establish that the DLL is the approved publisher artifact.

Download using the immutable revision in the URL and verify the complete bytes before extraction or activation. Extract only the expected DLL member. The Python package and native-engine wheel are distinct files; installing the former alone normally triggers a native download on first use.

Sources: [official engine artifacts](https://huggingface.co/Cactus-Compute/needle3/tree/c7c415a3d1b3d929014bc6e866d51ebb971f7089/python), [official speech artifacts](https://huggingface.co/Cactus-Compute/whistle/tree/b358ddadd89b7a713b5aa131f23032d3cca1b251), [PyPI release metadata](https://pypi.org/pypi/cactus-needle/3.1.0/json).

## Local files and networking

Set `NEEDLE3_LIB_PATH` to the local DLL **before creating the model**, and pass the local `.cact` explicitly through `weights`. `NEEDLE_LIB_PATH` refers to the older Needle 2 engine and must not be used for Whistle. The alternative weights override is `NEEDLE_WHISTLE_WEIGHTS`.

The package defaults to user-profile caches under `~/.cache/cactus-needle/v3/3.1.0` and `~/.cache/cactus-needle/whistle/2.0.0`. Explicit local paths avoid those caches and automatic runtime/model downloads. Set `HF_HUB_OFFLINE=1` for the running application after setup. Its microphone path needs `numpy`, `sounddevice`, and `soxr`; resample the device's native sample rate to 16 kHz before inference.

Disable publisher usage telemetry before imports with `NEEDLE_TELEMETRY=0` and `DO_NOT_TRACK=1`. The top-level `needle.transcribe` wrapper otherwise schedules an anonymous telemetry request, and telemetry may create a user-profile identifier file. Direct `Whistle.transcribe` currently has no such tracking call, but explicit disabling remains prudent across version changes.

Sources: [engine lookup and overrides](https://github.com/cactus-compute/needle/blob/main/needle/__init__.py), [download/cache behavior](https://github.com/cactus-compute/needle/blob/main/needle/agent/fetch.py), [telemetry implementation](https://github.com/cactus-compute/needle/blob/main/needle/_telemetry.py), [declared microphone dependencies](https://github.com/cactus-compute/needle/blob/main/pyproject.toml).

## Version caveats

These pins freeze the artifacts inspected here. The article's first-token measurements use an Apple M4 Pro and completed audio clips; they are not Windows latency guarantees. Model download size is about 16.9 MB, but process memory and application installation size are larger. Keyword biasing is decoding customization, not speech fine-tuning. The documented Needle training workflow targets text/tool calls; a supported Whistle speech adaptation and export pipeline has not been established by this project.
