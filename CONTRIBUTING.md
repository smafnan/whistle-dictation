# Contributing

Whistle Dictation is an early Windows desktop application. Contributions should
preserve its focus, cancellation, local-processing, and data-retention contracts.

## Development setup

Use 64-bit Python 3.12 on Windows and follow [DEVELOPMENT.md](docs/DEVELOPMENT.md).
Run `Setup.ps1` to install dependencies and verified model artifacts into the checkout.
No microphone or keyboard input is required for the unit suite.

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m ruff check src tests scripts launcher.py
.\.venv\Scripts\python.exe -m pytest -q -m "not integration" -p no:cacheprovider -p no:faulthandler
```

Changes involving microphone capture, focus, text delivery, process lifetime, or
settings need tests for their failure boundaries. Keep native integration tests
separate from unit tests; use explicit synthetic fixtures and avoid real recording
or typing during unattended CI.

## Pull requests

Describe the concrete behavior change, relevant validation, and any desktop
compatibility limits. Keep changes focused, update affected documentation, and
include an entry under an Unreleased section in `CHANGELOG.md` when appropriate.

Do not commit audio recordings, personal transcripts, logs, credentials, local
settings, downloaded models, virtual environments, or build output. Release
packages are assembled separately from source control.

## Reporting issues

Use the issue templates for reproducible bugs and feature requests. Include the
application version, Windows build, microphone/application involved, and exact
steps. Share only information necessary to reproduce the issue. Synthetic examples
are preferred over personal recordings. For vulnerabilities, follow
[SECURITY.md](SECURITY.md).

## Project license

Project source is licensed under MIT. Contributions are provided under the same
license. Third-party runtimes, models, libraries, and resources retain their own
licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).
