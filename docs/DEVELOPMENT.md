# Development guide

Whistle Dictation `v0.1.0` is a Python/Qt Windows application with a serialized
Whistle worker process and small native Win32 adapters. Read the
[architecture](ARCHITECTURE.md) for design decisions and the
[runtime findings](runtime-findings.md) for the speech API and artifact contract.
This guide covers development commands and the current packaging workflow.

## Prerequisites and setup

- Interactive Windows desktop session on AMD64 for native checks and packaging.
- 64-bit Python **3.12**, accessible through `py -3.12` or `python`.
- PowerShell and internet access for dependency/model setup.
- Microphone only for manual desktop acceptance; automated diagnostics do not
  capture live speech or deliver text to another application.

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1
```

The setup script creates `.venv/`, installs `requirements-dev.lock.txt`, downloads
the pinned native runtime and speech model, and runs the doctor. It requires exactly
Python 3.12, even though package metadata permits a wider interpreter range.
Use the checked setup workflow for the supported development environment.

| Option | Effect |
| --- | --- |
| `-SkipDev` | Install only `requirements.lock.txt`; omits test, lint, and packaging tools |
| `-SkipModel` | Skip model/runtime download and doctor; useful for tests using fakes |

The scripts set the source path directly, so no editable install is required.
Running `pip install` for the package alone does not provision this application's
local pinned `models/` layout; use setup or the explicit download command.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `src/whistle_dictation/app.py` | Tray/UI controller and coordination of capture, recognition, and delivery |
| `src/whistle_dictation/ui.py` | Main window, passive indicator, settings dialog, and styling |
| `src/whistle_dictation/session.py` | State transitions, request identity, and stale-result rejection |
| `src/whistle_dictation/audio.py` | Bounded microphone capture, resampling, silence handling, and segmentation |
| `src/whistle_dictation/engine.py` | Single worker process, shared audio transport, deadlines, and cleanup |
| `src/whistle_dictation/win32.py` | Global shortcut, destination capture, Unicode input, and single-instance guard |
| `src/whistle_dictation/config.py` | Validated settings and atomic persistence |
| `src/whistle_dictation/text.py` | Conservative cleanup and non-cascading phrase replacements |
| `src/whistle_dictation/runtime.py` | Pinned downloads, artifact verification, and local runtime environment |
| `tests/` | Audio, settings, formatting, state, native adapter, controller, and worker contracts |
| `scripts/` | Verification, packaging, preview, and license collection helpers |
| `WhistleDictation.spec` | PyInstaller one-folder windowed build |
| `docs/` | User documentation, design, validation, and acceptance procedures |

`.venv/`, `.cache/`, `data/`, `models/` artifacts, `build/`, and `dist/` are generated
locally and excluded from source control. Do not add recorded speech, settings,
logs, model weights, or compiled distributions to normal source commits.

## Run locally

```powershell
.\Run.cmd
```

To start with only the tray visible:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Run.ps1 -Hidden
```

For console diagnostics or a temporary shortcut override:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
.\.venv\Scripts\python.exe -m whistle_dictation --hotkey Ctrl+Alt+Shift+F12
```

Choose an available combination. The override affects this launch; subsequent
settings saves use the currently loaded settings. Ordinary app launch enforces
one instance per Windows session.

## Automated checks

The combined script runs lint, the test suite, native doctor, and offscreen startup:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test.ps1
```

For fast tests without downloaded runtime artifacts:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests scripts launcher.py
.\.venv\Scripts\python.exe -m pytest -q -m 'not integration' -p no:cacheprovider
.\.venv\Scripts\python.exe -m pip check
```

Tests use `src/` through pytest configuration. Native integration tests are marked
`integration`; they skip when their Windows runtime prerequisites are unavailable.
The real speech/shared-memory test also requires `.cache/speech-smoke.wav`, which
is not distributed as a repository fixture. A fresh checkout may therefore show
skips even after setup. Review the skip reasons rather than treating them as
equivalent to native coverage.

If reproducing the initial validation run's Windows process-creation diagnostics,
the recorded suite command disables pytest's faulthandler plugin:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -p no:faulthandler --basetemp=.cache\pytest-release
```

The [validation record](VALIDATION.md) explains the observed host diagnostic.
Passing adapter fakes and offscreen tests does not establish actual microphone
drivers, browser field identity, or native insertion compatibility.

## Native diagnostics and speech verification

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
.\.venv\Scripts\python.exe -m whistle_dictation --doctor
.\.venv\Scripts\python.exe -m whistle_dictation --smoke-test
.\.venv\Scripts\python.exe -m whistle_dictation --transcribe .\sample.wav
```

| Command | What it checks |
| --- | --- |
| `--doctor` | Artifact verification, actual model load, empty result on synthetic silence, input enumeration, and Win32 input layout |
| `--smoke-test` | Offscreen Qt startup, temporary `Ctrl+Alt+Shift+F24` registration, spawned worker readiness, and clean shutdown |
| `--transcribe` | Raw recognition of a supplied WAV of at most 30 seconds; no saved formatting/settings or insertion |
| `--download-model` | Explicit online provisioning of the pinned runtime/model into the app root |

These checks do not record live audio or type into another application. Run the
synthetic multi-segment speech check separately:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\VerifySpeech.ps1
```

This uses Windows speech synthesis to create `.cache/speech-long.wav` from
`tests/fixtures/synthetic-reference.txt` without playing it. The Python verification
helper resamples, segments, transcribes, and scores it, writing aggregate results
to `.cache/speech-validation.json`. This command does not create the distinct
`speech-smoke.wav` fixture used by the integration test described above.
Synthetic speech checks decoding and boundary handling; it is not a benchmark
of the intended user's accent, microphone, or stop-to-editor latency.

For live end-to-end checks, follow [ACCEPTANCE.md](ACCEPTANCE.md), record the actual
application/device versions and outcomes, and update validation evidence separately
from automated results.

## Build the portable application

After full setup and successful checks:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Build.ps1
```

The output is `dist/WhistleDictation/WhistleDictation.exe` with supporting files.
The build script copies the pinned `models/` artifacts, portable README, detailed
documentation, third-party notice, and collected dependency licenses. The spec
uses a windowed one-folder build; keep the complete output directory together.
Build on the intended platform rather than treating this as a cross-compilation
workflow. The validated output is Windows AMD64 and currently unsigned.

The portable app resolves its root beside the executable and creates a new
`data/` directory there. Source settings and logs are not intentionally copied
into a fresh build. If reusing a previous output directory, inspect it for old
mutable files before creating a distribution archive.

Create the distributable ZIP and checksum file with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\PackageRelease.ps1
```

The script reads the project version and writes
`releases/WhistleDictation-v0.1.0-windows-x64.zip` plus `releases/SHA256SUMS.txt`
for this version. It checks the AMD64 manifest and required files, keeps the
complete portable folder layout, and excludes `data/`, logs, WAV files, and
common sensitive file types. Generated archives belong in release assets rather
than source commits. Review the actual archive contents before uploading it.

Validate the packaged build's startup, local artifact load, and clean shutdown
in addition to source tests. For a release, also run the target-application and
live-microphone checks appropriate to the release claims. The initial packaged
doctor and offscreen smoke results are documented in [VALIDATION.md](VALIDATION.md);
they do not establish the outstanding desktop acceptance rows.

## Preserve the implementation boundaries

- Keep the native model on one serialized worker process. Do not call it from the
  GUI thread or concurrently initialize other Needle models in the same worker.
- Bind results to request IDs and retain cancellation/focus checks through delivery.
- Own and release shared audio in the parent on success, error, cancellation,
  timeout, and shutdown. Metadata queues must not carry the large audio arrays.
- Keep microphone callbacks bounded; perform device stop/close from controller code.
- Preserve the clipboard during automatic insertion and do not silently retry
  partial delivery, reactivate a destination, or synthesize submit commands.
- Keep normal logs free of transcripts, samples, dictionary entries, and window titles.
- Update runtime revisions and expected hashes together only after inspecting the
  upstream artifact and rerunning native checks.

See the architecture for the reasoning behind these contracts. Add focused tests
for changed behavior, especially lifecycle or native boundaries, and avoid tests
that merely duplicate implementation details.

## Documentation and version maintenance

The package version is declared in `pyproject.toml` and
`src/whistle_dictation/__init__.py`. Keep them aligned with the release tag and
release notes. Document behavior that users can actually exercise, and distinguish
automated contracts, synthetic speech, and manual desktop evidence.

When changing settings, command-line flags, dependencies, or packaging, update
the relevant user/development instructions and examples. Historical benchmark
and executable hashes in the validation record describe that specific build;
record new measurements instead of carrying them forward as unqualified claims.

Third-party components retain their own terms. Review [THIRD_PARTY.md](../THIRD_PARTY.md)
and the collected license resources when preparing a portable distribution.
