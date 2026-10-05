# Changelog

Changes to Whistle Dictation are recorded here. Versions follow semantic versioning;
the 0.x series is an early release while desktop compatibility is evaluated.

## [0.1.0] — 2026-10-05

First release of local Windows hotkey dictation.

### Added

- Windows tray application with a configurable global toggle shortcut.
- A passive recording indicator and microphone preview.
- CPU speech recognition using the pinned Cactus Whistle model and Windows runtime.
- Unicode text insertion at the original focused native control, with transcript
  recovery when the target changes or delivery fails.
- English, German, French, Spanish, Italian, Dutch, Polish, and language detection.
- Personal dictionary keyword biasing, exact phrase replacements, and optional cleanup.
- Quiet-boundary segmentation into clips of at most 28 seconds for long recordings.
- Bounded recording duration and 96 MB raw-audio budget.
- Isolated speech worker, shared-memory audio transport, cancellation, timeouts,
  retry, and cleanup after worker failures.
- Artifact integrity checks, offline operation after setup, and disabled telemetry.
- Portable Windows AMD64 executable, source setup scripts, test/build tools,
  professional documentation, and GitHub Actions CI.

### Validation

- 156 automated tests and 19 subtests passed on the original Windows AMD64 machine.
- Native runtime, offscreen application startup, and packaged executable checks passed.
- A 51-second generated speech clip decoded in two segments, with 1.87% normalized
  word error rate in that synthetic trial. This is not personal-voice accuracy evidence.
- Immediate cancellation with large audio and settings released shared memory and
  queue feeder threads.

### Known limitations

- Live microphone and application-specific insertion checks remain desktop acceptance work.
- Browser and Electron fields can share native handles, limiting field-change detection.
- Elevated applications can block input; partial insertion is possible and is not retried.
- Output is one line; spoken words are not interpreted as keyboard commands.
- Windows ARM64 artifacts are available upstream but this release was tested on AMD64.
- Meeting translation and speech fine-tuning are outside this release.

[0.1.0]: https://github.com/smafnan/whistle-dictation/releases/tag/v0.1.0
