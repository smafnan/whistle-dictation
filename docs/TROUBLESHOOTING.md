# Troubleshooting

Start with **Test microphone**. A successful preview separates recognition from
text insertion; a successful Notepad trial then checks native delivery. For
installation and normal use, see the [README](../README.md) and
[user guide](USER_GUIDE.md).

## Setup or startup

| Symptom | Action |
| --- | --- |
| Setup asks for Python 3.12 | Install 64-bit Python 3.12 and rerun `Setup.ps1`. The setup script intentionally checks this exact version. |
| Download or dependency installation fails | Check connectivity and rerun setup. Model and runtime downloads use fixed revisions and hash verification. |
| Runtime is not ready or a checksum mismatch is reported | For a source install, rerun `Setup.ps1` while connected. For portable use, extract a fresh complete release archive. |
| Permission error creating settings/logs | Move the complete app folder to a directory writable by your account. The app writes `data/` beside its executable or under the source project. |
| Portable app fails after moving the EXE | Restore the whole release folder, including `_internal/` and `models/`. The executable is not a standalone single-file package. |
| Another instance is already running | Use the existing tray icon, or quit that instance before launching again. Only one ordinary app instance is supported in the Windows session. |
| Notification tray unavailable | Run in an interactive Windows desktop session. The tray app is not designed as a headless service. |
| Engine enters an error state | Use **Retry engine**. If it fails again, inspect the status and run source diagnostics when available. |

The AMD64 build is the validated platform. The downloader includes ARM64 artifacts,
but that execution path has not been validated by this project.

If Windows warns about the unsigned portable build, review the release origin
and published checksums. This project does not supply code signing in `v0.1.0`.

## Shortcut does not start listening

Open the main window and confirm that the engine is **Ready** and the Settings
dialog is closed. A second shortcut press stops recording; presses while the
engine is processing do not start another session.

If the status says **Shortcut unavailable**, choose a different combination in
**Settings**. Windows or another application may already own the requested
shortcut. Saving a conflicting replacement shortcut does not discard the previous
working configuration.

The default is **Ctrl+Alt+Shift+Space**. Release the modifier keys after stopping
recording: input delivery waits briefly for held modifiers and can stop if they
remain pressed.

## Microphone does not record

1. Confirm that the device is connected, unmuted, and working in Windows sound
   settings or a recording application.
2. Allow microphone access for desktop applications in Windows privacy settings.
3. In **Settings**, select the correct input device or **Windows default microphone**.
4. Run **Test microphone**, speak, and stop the recording.

Device indices can change after unplugging devices, restarting drivers, or changing
audio hardware. Reselect the microphone when necessary; a saved unavailable device
is displayed as such rather than silently treated as a different microphone.
The model doctor enumerates devices but does not record from them.

If the app reports **Microphone lost audio**, review the transcript. Automatic
insertion is suppressed because the recording may contain gaps. Reduce competing
workload, check the device/driver, and retry with a short preview.

## Recognition is empty, inaccurate, or slow

- Choose the intended spoken language explicitly when establishing a baseline.
  The available languages are English, German, French, Spanish, Italian, Dutch,
  and Polish. Urdu is not supported by this app's language configuration.
- Check microphone placement and input level with a short preview in a quiet room.
- Add recurring names or technical terms to the personal dictionary, then compare
  otherwise identical recordings. Use exact replacements only for narrow,
  repeatable errors.
- Use shorter dictations while investigating delays. The app transcribes completed
  recordings; it does not stream text into your editor while you speak.
- Review words near 28-second segment boundaries in long recordings. Current
  synthetic-speech validation does not establish your voice's recognition quality.

If the inference deadline expires, the engine enters an error state; **Retry engine**
starts a new worker. Advanced users can adjust `inference_timeout_seconds` in the
settings file while the app is closed. A longer timeout changes the failure
deadline, not processing speed. The displayed duration is worker processing time,
not the full time from pressing Stop until the destination accepts the text.

The publisher's model benchmarks and the project's synthetic results are not
latency guarantees for your machine. Use the [acceptance procedure](ACCEPTANCE.md)
for repeatable local measurements.

## Transcript appears in the app but not in the textbox

First test a new Notepad document using the global shortcut. **Test microphone**
is intentionally a preview and never inserts text into another application.

For ordinary dictation, the destination must remain focused. The app checks the
original foreground window, native focused control, and process before and during
delivery; changing those can stop insertion. It does not reactivate the original
window. Open the app, review the transcript, and copy it explicitly when needed.

Some applications do not accept simulated Unicode keyboard input. Elevated
applications can reject input from this normal-user app. Use manual copy/paste as
the fallback and record the field as unsupported for automatic insertion until
it passes a desktop trial.

The focus checks cannot identify every visual textbox within a browser or Electron
window. Avoid switching fields, tabs, or editor surfaces during recording and
processing, even if the foreground window appears unchanged.

## Only part of the text appears

Focus can change or Windows can block input midway through delivery. The app
stops and keeps the complete transcript; it does not retry automatically.
Inspect the destination before pasting, because it may already contain a prefix.
If replacing it with the full transcript, remove the prefix first to avoid
duplication.

Windows accepting simulated input packets does not prove that the destination
processed every character. Repeat the application's acceptance trials with
disposable text before declaring it compatible.

## Settings are invalid

The Settings dialog checks values before saving. For manual JSON edits, quit the
app first and check the supported schema in
[settings.example.json](../settings.example.json). Unknown keys, malformed JSON,
invalid shortcut syntax, and out-of-range values are rejected.

To recover, rename `data/settings.json` while the app is closed and restart to
use defaults. Keep the renamed file to recover dictionary entries. This operation
does not require deleting the model files or reinstalling dependencies.

## Source diagnostics

From the source repository root, after setup, run:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
.\.venv\Scripts\python.exe -m whistle_dictation --doctor
.\.venv\Scripts\python.exe -m whistle_dictation --smoke-test
```

The doctor verifies model/runtime hashes, loads Whistle, checks a synthetic silent
clip, enumerates input devices, and prints a JSON report. It does not open the
microphone or type text. The offscreen smoke check exercises GUI startup, a
temporary native shortcut, the worker, and shutdown; it also does not record or
insert text. The portable executable is a windowed build, so source commands are
the documented way to obtain visible diagnostic output in a console.

To isolate recognition on an existing short WAV file:

```powershell
.\.venv\Scripts\python.exe -m whistle_dictation --transcribe .\sample.wav
```

This diagnostic prints raw recognition output without applying the app's saved
dictionary/replacements or inserting text. Supply a WAV of no more than 30 seconds;
the tray app's long-recording segmentation is not applied by this command.

## Report a problem

Open an [issue](https://github.com/smafnan/whistle-dictation/issues) with the app
version, Windows version and architecture, installation method, steps to reproduce,
expected result, actual status message, and destination application/version if
insertion is involved. Mention whether **Test microphone**, Notepad insertion,
doctor, and smoke checks succeeded when applicable. For device problems, include
the microphone model and whether you selected a device or the Windows default.

Review diagnostics before sharing them. Doctor output contains the local root
path and device names; the settings file can contain personal dictionary entries.
Normal app logs omit speech content, but any screenshots, WAV files, or sample
transcripts you attach can contain private information. A redacted short example
and the exact status message are usually enough to start investigating.
