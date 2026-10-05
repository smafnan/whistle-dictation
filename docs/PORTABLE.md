# Whistle Dictation — portable Windows app

Keep this entire folder together. Double-click **WhistleDictation.exe**; no separate
Python installation is required. Wait for the status to say **Ready**.

1. Open a textbox in Notepad or another application and leave it focused.
2. Press **Ctrl+Alt+Shift+Space** to start recording.
3. Speak, then press the shortcut again to stop.
4. Wait for the completed text to appear. Do not change fields while it processes.

The passive recording indicator leaves keyboard focus in your application.
Recognition runs locally. Automatic insertion leaves your clipboard unchanged and
never presses Enter. Closing the main window keeps the tray app running; use the tray
menu to quit. The app does not add itself to Windows startup.

Use **Test microphone** to preview speech recognition without entering text in another
app. **Settings** changes the shortcut, microphone, language, dictionary, replacements,
and basic cleanup. **Copy transcript** deliberately replaces your clipboard with the
latest transcript. If a shortcut is already taken, choose another in Settings.

Longer recordings are split into clips of at most 28 seconds. Capture is bounded by
the configured duration and a 96 MB sample budget. Cancellation destroys a processing
worker and reloads it; cancelled results cannot later be inserted.

If the foreground window, native text control, or process changes, the app stops
insertion and keeps the transcript for review/copying. Browser/Electron fields can
share native handles: avoid changing textboxes within the same window during dictation.
Some applications block simulated Unicode input, especially elevated applications.
If delivery is partial, inspect the destination before manually pasting the full text.

Place this folder somewhere you can write to, such as a folder under your user account.
Settings and metadata-only logs are created in **data/** beside the executable.
Audio and transcripts are not saved. **models/** contains the verified local runtime
and model; **licenses/** contains upstream license resources.

The source project includes detailed architecture, acceptance checks, setup/build/test
scripts, and measured validation. Start with **docs/USER_GUIDE.md**
and **docs/TROUBLESHOOTING.md**. The bundle also includes
**docs/ARCHITECTURE.md**, **docs/ACCEPTANCE.md**, **docs/VALIDATION.md**,
and **docs/app-preview.png**.

The initial build has automated and synthetic-speech validation. Your live microphone
and intended application fields still need the short manual checks in the acceptance
document. It uses the base Whistle model with vocabulary customization; no speech
fine-tuning has been performed.

Application source is MIT licensed; see **LICENSE** in the bundle. Dependencies
and model weights retain their own terms; see **THIRD_PARTY.md** and **licenses/**.
Source and release updates are available at
[smafnan/whistle-dictation](https://github.com/smafnan/whistle-dictation).
