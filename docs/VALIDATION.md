# Validation record — 5 October 2026

Platform: Windows 11 AMD64 (build 26200), Python 3.12.10,
PySide6 6.11.2, cactus-needle 3.1.0. Artifact hashes and immutable model/runtime
revisions are in `runtime-findings.md` and `models/manifest.json`.

## Completed source validation

- **156 tests and 19 subtests passed** in the final combined run (3.80 seconds).
  Includes synthetic audio, native adapter fakes, real offscreen Qt controller,
  settings/modal guards, cancellation, stale IDs, shared-memory ownership,
  process crash/deadline recovery, and native runtime integration.
- Ruff passed across `src`, `tests`, `scripts`, and the launcher.
- `pip check` reported no broken requirements.
- All PowerShell scripts parsed successfully.
- Native doctor loaded Whistle, recognized synthetic silence as empty, enumerated
  input devices, and verified 40-byte Windows `INPUT` layout.
- Offscreen source smoke passed: actual Qt, temporary native F24 hotkey, spawned
  model worker, and clean shutdown. No live recording or keyboard injection occurred.
- Immediate cancellation of 32 MB synthetic audio left no shared-memory allocation
  or queue feeder thread. The same test with maximum-sized settings metadata passed.

Final suite command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -p no:faulthandler --basetemp=.cache\pytest-release
```

Pytest's faulthandler emitted Windows exception diagnostics inside process creation
in an earlier passing run. The clean run disabled that diagnostic plugin; all native
child processes, integration assertions, and standalone worker checks completed
successfully. This is an observed host test diagnostic, not evidence of an app crash.

## Native speech evidence

A generated SAPI short sentence was transcribed exactly:

> This is a test of local voice dictation. Please schedule a meeting for tomorrow morning.

One run reported first-token time 797.8 ms and decoding 140.5 tokens/second.

The longer synthetic verification produced:

| Measurement | Result |
| --- | --- |
| Input | 51.1114 seconds, mono 22,050 Hz PCM |
| Processing | Resampled to 16 kHz, two segments under 28 seconds each |
| Recognition and formatting time | 10.976 seconds |
| Model load in that run | 0.0257 seconds |
| Normalized word error rate | 1.869% |
| Observed error | `tomorrow` was split into `to morrow` |

Normalization casefolds Unicode word tokens and ignores punctuation. The report
is generated at `.cache/speech-validation.json` by `scripts/VerifySpeech.ps1`.
This validates real decoding and long-recording handling on synthetic speech.
It does not measure the user's voice, accent, microphone, or editor latency.

## Portable executable

The final executable includes shared-memory transport, microphone cleanup, and
the modal Settings guard. Both final packaged checks passed with exit code **0**:

- Offscreen Qt/hotkey/spawned-model-worker startup and shutdown.
- Native model doctor, synthetic silence, and input-device enumeration.

Executable: `dist/WhistleDictation/WhistleDictation.exe`.
SHA256: `3fe7b422955074d72c01f1833c174ce3a0d4edf9e840e4e4306114808ba946ff`.
The portable folder is approximately 184 MB before documentation; Qt/Python and
other dependencies account for most of its size. Keep the whole folder together.

## Still requires desktop acceptance

Live microphone capture, actual Unicode delivery to Notepad/VS Code/browser/Word,
focus changes within browser fields sharing one native handle, real-device overflow,
and accuracy on the user's speech remain manual acceptance work. No real user audio
was captured and no keyboard input was injected during this development run.

Use `ACCEPTANCE.md` for the application matrix and representative speech evaluation.
No speech fine-tuning or personal-voice accuracy claim is included in this release.
