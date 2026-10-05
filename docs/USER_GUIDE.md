# User guide

This guide covers Whistle Dictation `v0.1.0`. For installation, start with the
[repository README](../README.md). This release is an experimental Windows tray
application; test your microphone and intended text fields before relying on it
for daily use.

## Start and check your microphone

Open `WhistleDictation.exe` in a portable installation, or `Run.cmd` in a source
installation. Wait until the status says **Ready**. If the tray icon is hidden,
look in the notification area's overflow menu.

1. Click **Test microphone**.
2. Speak a short, ordinary sentence.
3. Click **Stop recording**, or press the configured shortcut again.
4. Review **Last transcript**. This preview records and transcribes without
   inserting text into another application.

If you do not see your speech, open **Settings**, select an input microphone,
and repeat the preview. Choosing an explicit spoken language is a useful starting
point when evaluating recognition. See [troubleshooting](TROUBLESHOOTING.md)
for permission and device problems.

## Dictate into a field

1. Click the intended editable field, with the cursor at the desired position.
2. Press **Ctrl+Alt+Shift+Space**, or your configured shortcut, to start listening.
3. Speak normally. A small indicator displays the elapsed recording time.
4. Press the same shortcut again, release the keys, and wait for processing.
5. The app sends the completed transcript as Unicode keyboard input.

Text follows the receiving application's normal cursor and selection behavior.
The app does not inspect the field's content or decide whether it is semantically
editable. Start in a disposable Notepad document when checking insertion for
the first time.

Keep the same application and field focused through recording and processing.
The passive indicator is designed to avoid activating a window. Opening the
main app, changing applications, or selecting another native control can stop
delivery. Visual fields in browsers and Electron applications can share a native
handle, so a switch between those fields may go undetected.

Only the final transcript is inserted; partial text does not appear while you
speak. Automatic insertion leaves the clipboard unchanged and does not press
Enter, submit forms, or interpret phrases such as "new line" as commands.
Control characters are removed and the result is delivered as one line.

## Tray controls and cancellation

Double-click the tray icon to open the app. Right-click it to access its menu.

| Control | Behavior |
| --- | --- |
| **Open Whistle Dictation** | Show the main window and its last transcript |
| **Cancel dictation** / **Cancel** | Discard the active recording or invalidate active transcription |
| **Copy last transcript** / **Copy transcript** | Replace the clipboard with the last transcript |
| **Clear transcript** / **Clear** | Remove the transcript from the app's display |
| **Settings** | Change settings while the app is not recording or processing |
| **Retry engine** | Start a fresh recognition worker after an engine error |
| **Quit** | Stop the microphone, unregister the shortcut, and close the app |

Cancellation during listening discards captured audio. Cancellation during
processing terminates the worker and reloads the engine; wait for **Ready**
before starting again. Cancelled requests cannot subsequently insert their text.
An earlier completed transcript may still be visible until you clear it or a
new result replaces it.

Closing the main window hides it while the tray app continues running. The app
does not automatically start with Windows.

## Settings reference

Use **Settings** while idle. Save your changes and close the dialog before
starting dictation. Each recording uses the settings captured when it starts.

| Setting | Default | Meaning |
| --- | --- | --- |
| Global shortcut | `Ctrl+Alt+Shift+Space` | Toggle recording from another application |
| Spoken language | English (`en`) | Choose English, German, French, Spanish, Italian, Dutch, Polish, or automatic detection |
| Microphone | Windows default | Use the current default input device or select a listed device |
| Recording limit | 300 seconds | Automatic stop, configurable from 10 to 900 seconds |
| Capitalization and cleanup | Enabled | Capitalize the first character and remove spaces before punctuation |
| Final period | Disabled | Append a period when the transcript does not already end in recognized terminal punctuation |
| Space after inserted text | Enabled | Add one space for automatic insertion; it is not added to the displayed/copied transcript |
| Personal dictionary | Empty | Bias decoding toward up to 128 words or phrases |
| Exact replacements | Empty | Replace up to 128 whole words or phrases after recognition |

The shortcut accepts combinations of `Ctrl`, `Alt`, and `Shift`, with a letter,
digit, supported named key, or function key; it must include `Ctrl` or `Alt`.
Windows may reserve a combination
or another application may already own it. If a replacement shortcut cannot be
registered, the app keeps the prior settings and shortcut.

### Personal dictionary

Enter one word or phrase per line, for example:

```text
Whistle
Cactus
Project Atlas
```

Each phrase must be non-empty, single-line text of at most 120 characters.
Dictionary entries influence recognition; they do not guarantee an exact match
or train the speech model. Use terms you actually dictate, then compare results
with and without the dictionary.

### Exact replacements

Enter one rule per line using `source => replacement`:

```text
project at less => Project Atlas
```

Rules match whole words/phrases, case-insensitively, rather than arbitrary parts
of a word. Longer source phrases take priority over overlapping shorter ones.
Replacements are applied once, so replacement text is not fed through additional
rules. Source phrases can contain up to 120 characters and replacements up to
500; both must be single-line text. An empty replacement removes a matched term.

Keep rules narrow: a broadly used source phrase can change valid speech too.
Recognition, exact replacements, and conservative cleanup are separate steps;
the app does not rewrite sentences using another language model.

### Settings file

Settings are saved to `data/settings.json` under the source project or beside
the portable executable. [settings.example.json](../settings.example.json)
shows the schema; it is an example, not automatically loaded.

An advanced `inference_timeout_seconds` field is available in the JSON file
with a default of 180 seconds and an allowed range of 15–600. It is not exposed
in the Settings dialog. Quit the app before manually editing the file, keep a
backup, and use valid JSON. Unknown fields and invalid values are rejected.
To restore defaults, quit, rename the settings file, and restart. Preserve the
renamed copy if you want to recover your dictionary.

## Longer recordings

Whistle accepts at most 30 seconds per recognition pass. The app resamples your
recording to mono 16 kHz and divides it into clips no longer than 28 seconds,
preferring quieter split points. Results are combined and formatted before
one delivery attempt. The displayed segment count describes this processing.

Capture ends at your duration limit or 24 million raw float32 samples, whichever
comes first. The sample budget is 96 MB: at a 48 kHz input rate it holds about
500 seconds. Application memory usage is higher because processing and the
interface require additional buffers. When capacity is reached, the app processes
the retained recording automatically and displays a notice.

Start with short dictations and check speech near split boundaries when testing
longer recordings. Long-clip accuracy on your voice remains a manual evaluation.

## Recover a transcript

The latest result appears in the main app whether insertion succeeds or needs
attention. If the app reports changed focus, lost audio, blocked input, or
incomplete insertion:

1. Open the app and review the transcript.
2. Inspect the destination for a partially inserted prefix.
3. Click **Copy transcript**, return to the intended field, and paste only what
   you need. Remove any existing prefix first if replacing it with the full text.

There is no automatic retry after partial insertion because it could duplicate
text. Lost microphone audio also suppresses automatic insertion so you can review
the result. Transcript recovery retains only the latest result in memory; it is
not a persistent history.

## Privacy and files

| Location | Contents and retention |
| --- | --- |
| App memory | Captured audio during processing and the latest displayed transcript; no normal-operation disk recording |
| `data/settings.json` | Saved shortcut, microphone index, language, dictionary, replacements, and processing options |
| `data/app.log` and rotated copies | Operational events, durations, counts, and error categories; no speech content or window titles |
| `models/` | Local pinned runtime, model, and artifact manifest |
| `.cache/` in source installs | Setup downloads and development/test artifacts |

Logs rotate at approximately 256 KB with two backups. Dictionary entries and
replacement text are stored in your settings even though they are excluded from
the operational logs. The runtime is configured offline with telemetry disabled;
initial setup downloads dependencies and model artifacts.

**Copy transcript** explicitly places text on your clipboard, where Windows
clipboard features and other applications may retain it. Text inserted into
another application follows that application's storage and sharing behavior.
Development speech verification deliberately writes synthetic WAV files under
`.cache/`; it does not change normal dictation retention.

For desktop compatibility and speech evaluation, use the
[acceptance checklist](ACCEPTANCE.md). For the exact checks completed on the
initial build, read the [validation record](VALIDATION.md).
