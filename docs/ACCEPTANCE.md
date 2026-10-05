# Whistle Dictation acceptance and evaluation

Baseline: 5 October 2026. This checklist establishes whether the implemented
prototype meets the user's dictation needs on their Windows machine.
Quantitative criteria below are initial engineering targets, not measured
accuracy, compatibility, latency, or memory claims.

## Evidence boundaries

Automated tests exercise synthetic audio and fake microphone/native/model
adapters. They establish application contracts without recording a real
microphone or typing into another application. The audio suite currently has
25 passing tests, including real soxr tone/duration verification. The other
suites cover settings, formatting, session identity, worker behavior, runtime
integrity, native input contracts, and the real offscreen Qt controller using
fake peripherals. Final source validation passed 156 tests plus 19 subtests in
3.80 seconds. Ruff and `pip check` were clean, and the final source offscreen
real Qt/native-hotkey/spawned-worker smoke check succeeded. See
[VALIDATION.md](VALIDATION.md) for the consolidated run record.

`--doctor` verifies artifacts, loads the actual model, transcribes synthetic
silence, and lists input devices. Listing a microphone does not prove capture
works. `--smoke-test` creates the Qt controller, registers a hotkey, loads the
worker, and exits cleanly when ready; it neither captures live audio nor invokes
native insertion. Record the observed outcomes rather than inferring them from
available commands.

The local Windows AMD64 doctor has succeeded: actual model load took 65 ms,
one second of synthetic silence returned empty text, input devices enumerated,
and the native `INPUT` structure was 40 bytes. The offscreen real Qt/native
hotkey/spawned Whistle worker/startup/shutdown check also succeeded, using
`Ctrl+Alt+Shift+F24` as an isolated test shortcut.

A generated Windows SAPI English WAV was recognized exactly as: “This is a
test of local voice dictation. Please schedule a meeting for tomorrow morning.”
Its reported first-token time was 797.8 ms and decode throughput 140.5 tokens
per second in that one local CPU run. This checks actual speech inference;
synthetic speech and model counters do not establish the user's voice accuracy,
live microphone behavior, stop-to-editor latency, or a general performance
benchmark. Live microphone recording and native insertion remain unvalidated.

The updated engine suite has 42 passing tests. Transport checks include a real
generated-speech shared-memory result and immediate cancellation with a 32 MB
audio buffer using both ordinary settings and maximum-size settings metadata
above 64 KB. The queue stress probe finished with only `MainThread`, with no
retained feeder thread. These checks establish transport teardown for those
tested cases; native desktop cancellation and microphone trials remain separate.

The longer generated-speech pipeline check used a 51.1114-second, mono 22,050 Hz
WAV. Actual resampling, segmentation, recognition, and formatting produced two
segments in 10.976 seconds, with 25.7 ms model load. Normalized WER was 1.87%
using casefolded Unicode word tokens with punctuation ignored; the observed
error was “tomorrow” rendered as “to morrow.” No omitted/repeated words at the
segment boundary were observed in that sample. Reproduce it with
`scripts/VerifySpeech.ps1`; its aggregate report is
`.cache/speech-validation.json`. This is one synthetic fixture, with pipeline
timing that excludes live capture, transport, and insertion.

The final rebuilt AMD64 portable executable, including the latest shared-memory
transport and settings validation, passed both doctor and offscreen smoke
checks with exit code 0. Its executable SHA-256 is
`3FE7B422955074D72C01F1833C174CE3A0D4EDF9E840E4E4306114808BA946FF`.
These checks establish packaging/startup on this machine rather than live
dictation compatibility. A clean-machine setup trial and ARM64 runtime execution
remain separate acceptance work.

| Evidence item | Result to record | What it establishes |
| --- | --- | --- |
| Automated suite | Command, test totals, failures, platform | Application contracts exercised by tests |
| Doctor | JSON report, architecture, model/runtime versions | Actual native initialization and synthetic-silence inference |
| Offscreen smoke | Exit code and output | Qt/hotkey/worker startup and cleanup |
| Live microphone preview | Device, speech phrase, transcript | Real capture plus native recognition |
| Native text insertion | Application/build, field, typed outcome | Real end-to-end destination compatibility |
| Speech evaluation | Dataset version, settings, WER, critical tokens | Recognition quality for intended voice and environment |
| Performance | Hardware, duration, quantiles, combined memory | Actual responsiveness and capacity |
| Offline trial | Network disabled, successful end-to-end flow | Local operation after setup |

A useful reproducible test command from the repository root is:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp .cache\pytest-acceptance
```

Use a fresh `--basetemp` location for each retained acceptance run. Follow
README instructions for dependency setup and the doctor/smoke launch scripts.

## Automated contract matrix

| Area | Cases covered | Test source |
| --- | --- | --- |
| Audio capture | Copied callback buffers; exact time/sample budget; overflow; restart; empty capture; abort/discard; start/stop/callback failure cleanup | `tests/test_audio.py` |
| Segmentation | Silence-aware boundary; short final tail; clips within 28 seconds; exact concatenation back to original samples | `tests/test_audio.py` |
| Resampling and silence | 48-to-16 kHz tone/duration; contiguous float32; empty/all-quiet input; short quiet phrase inside long silence | `tests/test_audio.py` |
| Native destination | Foreground/child/process changes; closed targets; focus change between batches | `tests/test_win32.py` |
| Input encoding | UTF-16, supplementary characters, bounded batches; rejected controls/surrogates; held modifiers; partial send without retry | `tests/test_win32.py` |
| Native lifecycle | Hotkey parsing/conflicts/dispatch/unregister; single-instance handle cleanup; Windows ABI sizes | `tests/test_win32.py` |
| Settings | Defaults, Unicode roundtrip, field validation, malformed input, atomic-save failure preserving prior settings | `tests/test_config_text_session.py` |
| Formatting | Conservative punctuation, whole-phrase replacements, non-cascading replacement, Unicode matching, control removal | `tests/test_config_text_session.py` |
| Session | Valid transitions, cancellation invalidating prior IDs/targets, stale response rejection, closed state | `tests/test_config_text_session.py` |
| Worker service | Single flight; language/keywords/progress; malformed output/errors; deadlines; crash/termination cleanup; startup failure; shared-audio ownership/release | `tests/test_engine.py` |
| Runtime | Verified cached download, integrity failure preserving prior file, corrupt artifact rejection, offline/local environment | `tests/test_engine.py` |
| Tray controller | Preview isolation; exactly-once result handling; stale/cancelled result rejection; overflow/manual recovery; settings snapshots; indicator flags; cleanup and retry | `tests/test_app.py` |

These tests do not establish browser DOM identity, actual `SendInput` behavior
under another application's integrity level, microphone driver behavior, or
recognition accuracy on speech.

## Manual application compatibility

Record the application version and actual Windows build. Start with a short
sentence containing plain English, punctuation, a number, and a dictionary
name. Use the same phrase and settings across apps where possible. Repeat each
supported field at least five times before declaring it accepted.

| Application / field | Required trial | Expected result | Status |
| --- | --- | --- | --- |
| Notepad | Empty field, mid-line cursor, selected text | Text enters once at current selection; indicator does not activate | Pending |
| VS Code | Ordinary editor; search input; editor with an active selection | Unicode delivery accepted; selection behaves as normal typing | Pending |
| Edge or Chrome | Plain `input`, `textarea`, contenteditable editor | Text appears once; no submission; native focus remains usable | Pending |
| Browser focus changes | Switch tab or visual field during recording/processing | Observe/document same-HWND limitation; do not claim semantic focus protection | Pending |
| Microsoft Word | Body paragraph, mid-sentence cursor, selected text | Text enters at selection; punctuation/spacing remain acceptable | Pending |
| Electron app | VS Code or another intended Electron app, main editor and secondary field | Assess Unicode support and same-HWND focus limitation | Pending |
| Elevated application | An elevated disposable text editor from a normal app process | Blocked/partial delivery reported; no automatic retry; transcript available | Pending |
| Non-editable target | Focused ordinary application surface without a textbox | Observe result; no semantic editable-field detection is claimed | Pending |

For native controls, changing the foreground window, focused child, process, or
closing the destination must prevent further insertion and retain the
transcript. For browser/Electron visual fields sharing an HWND, this guarantee
does not apply. Remain in the chosen visual field for supported dictation.
Test with disposable text; successful event submission is not an assertion
that every application handles the packets correctly.

For each ordinary insertion trial, record:

1. Existing clipboard text before and after; it should remain unchanged.
2. Whether a modifier was held after stopping; delivery should wait briefly or
   report a timeout with transcript retained.
3. Whether Enter, Tab, paste shortcuts, or form submission occurred; none is
   emitted by automatic delivery.
4. Whether the text appears once, with the expected trailing-space preference.
5. Whether opening the app reveals the same final transcript and status.

## Lifecycle and failure trials

| Scenario | Expected acceptance behavior | Status |
| --- | --- | --- |
| Launch / second launch | One tray instance; second instance reports already running | Pending desktop check |
| Reserved or already registered shortcut | Registration error is understandable; settings and preview remain usable | Pending desktop check |
| Save a conflicting replacement shortcut | Prior shortcut/settings remain usable | Pending desktop check |
| Close main window | Window hides; tray and shortcut continue working | Pending desktop check |
| Quit while idle, recording, processing | Microphone/hotkey/worker released; no later insertion | Pending desktop check |
| Microphone preview | Result stays in app; no external insertion | Pending live microphone |
| Microphone permission denied / missing device | Clear recoverable error; no text inserted | Pending live device |
| Disconnect / reconnect microphone | Failure or overflow surfaced; new recording can recover after reselection | Pending live device |
| 30-, 60-, and 300-second speech | Segments stay within model limit; all words checked near boundaries | Pending real speech |
| Time/sample capacity reached | Auto-stop within polling allowance; retained audio processed; capacity notice | Pending live capacity |
| Silent recording and short recording | No injected text; readiness restored | Pending live microphone |
| Input overflow | Transcript retained for review; automatic insertion suppressed | Fake callback verified; device stress pending |
| Cancel recording | Audio discarded; no delayed transcript or insertion | State/audio contracts tested; desktop trial pending |
| Cancel processing | Worker replaced; app reloads; stale result cannot insert | State/service contracts tested; native trial pending |
| Cancel with large submitted audio / maximum settings | Worker terminates; shared audio releases; metadata feeder terminates without retaining audio | 32 MB immediate-cancel/default and >64 KB metadata stress verified |
| Worker crash or inference timeout | Error state, useful status, Retry loads fresh worker | Service contracts tested; native trial pending |
| Target closed or switched native focus | Delivery stopped; transcript recoverable | Fake native adapter verified; desktop trial pending |
| Partially accepted input | Error without retry; inspect possible prefix before manual Copy | Fake adapter verified; native behavior pending |
| Network disabled after setup | Start, record, recognize, insert normally | Pending offline trial |
| Inspect app log after dictation | No transcript, raw audio, dictionary phrases, or window titles | Pending run review |
| Restart Windows without launching app | App does not automatically start | No startup integration implemented; desktop check pending |

A release for daily use requires the intended applications and devices to pass
their matrix rows. An unsupported application can still use preview plus
explicit Copy if that workflow is acceptable; record this as manual use rather
than successful automatic insertion.

## Speech dataset and baseline evaluation

Create 100–200 representative clips with manually checked reference
transcripts. Use the intended microphone, normal speaking voice, likely
background conditions, and real domain vocabulary. Do not automatically
repurpose meeting recordings; choose and label authorized recordings for this
evaluation. Keep the final evaluation clips fixed and out of dictionary
iteration or later training decisions.

| Stratum | Suggested share | What it tests |
| --- | ---: | --- |
| Ordinary clear dictation | 40% | Baseline sentences and common vocabulary |
| Technical/product/personal names | 20% | Keyword biasing and exact replacements |
| Numbers, dates, identifiers | 15% | Critical detail accuracy |
| Quiet speech or room noise | 15% | Gate calibration and noise tolerance |
| Long speech and boundary phrases | 10% | 28-second splitting and final tails |

Cover short 2–5-second phrases, typical 5–15-second dictation, and longer
30–90-second recordings. If German dictation is intended, evaluate German as a
separate stratum with its own references and scores. Report the language,
microphone, room, speaker/session, and duration for each clip. Accuracy on one
speaker/room is not evidence for another.

Evaluate at least two frozen configurations: baseline Whistle with explicit
language, and the same model with the personal dictionary. Treat replacement
rules as a third configuration because they can hide recognition errors or
introduce false corrections. Use raw transcription scores for recognition and
separate final-formatted scores for the actual delivered text.

WER is `(substitutions + deletions + insertions) / reference_word_count`.
Document tokenization, case, punctuation, and number normalization. Report
corpus-weighted WER and per-stratum WER; do not average percentages across clips
without accounting for reference length. Score names, numbers, and identifiers
separately with exact matches before and after replacement. Manually review
insertions during silence and words at segmentation boundaries.

Reserve about 20–30% of clips from separate sessions for final evaluation.
Choose dictionaries and replacements on the remaining development clips.
For future training, reserve speakers/sessions before creating train/dev/test
splits; do not evaluate on the same examples used to adapt the model.

Initial recognition targets for the primary user's clean English dictation:

| Metric | Initial target | Result |
| --- | --- | --- |
| Clean ordinary dictation WER | At most 10% | Not measured |
| Overall representative corpus WER | At most 15%, with noise strata reported separately | Not measured |
| Critical dictionary names/terms | At least 95% exact match on held-out examples | Not measured |
| Numbers/identifiers | Report exact-match score; any recurring important error requires review | Not measured |
| Silent clips | No automatic text insertion | Not measured on recorded silence |
| Vocabulary customization | Improve intended term accuracy without worsening ordinary speech materially | Not measured |

These targets are decision gates, not release claims. If the primary language,
accent, noise, or domain fails them, choose mitigation from observed errors:
microphone placement, explicit language, keyword biasing, narrow replacement
rules, or a different recognizer benchmark. Establish a workable Whistle speech
training/export pipeline before scheduling audio fine-tuning. Text/tool-call
fine-tuning is not speech adaptation.

## Latency, resource, and reliability evaluation

Measure microphone startup, stop-to-first-visible text, stop-to-final text,
processing time per clip, and model readiness separately. The tray application
inserts only after the complete recording is transcribed, so model first-token
latency is not application text latency. The transcript detail display measures
worker resampling/recognition/formatting; it excludes microphone stopping,
shared-memory allocation/copy, metadata transport, and actual editor acceptance.

Record CPU model, RAM, Windows build, architecture, power mode, input sample
rate, package/model revisions, settings, and competing load. Use a warm worker
for ordinary latency and report cold startup separately. Collect at least 30
dictations for useful P50/P95 summaries. Sample combined resident memory of the
Qt process and worker during idle, capture, concatenation, shared-memory copy,
and inference. Shared pages can appear in both process working sets; report
private commit and shared mapping size alongside summed RSS so the same mapping
is not mistaken for two separate physical copies. Verify released mappings
and terminated metadata feeder threads after cancellation, timeout, and Quit.

| Metric | Initial target | Result |
| --- | --- | --- |
| Listening indicator after shortcut | P95 within 200 ms | Not measured |
| Warm stop-to-final text, 2–10 s speech | P95 within 2 s | Not measured |
| Warm stop-to-final text, 30 s speech | P95 within 5 s | Not measured |
| Cold model/application readiness | Within 10 s on intended hardware | Not measured |
| Normal dictation peak combined RSS | Below 500 MB for short clips | Not measured |
| Capacity-limit stress combined RSS | Below 1 GB; raw capture remains at most 96 MB | Not measured |
| Supported ordinary app trials | No missing/duplicated delivery in 50 trials | Not measured |
| Cancel and Quit trials | No later inserted text; no retained microphone stream | Not measured on native desktop |

If a target fails, record the bottleneck and amend the design or the agreed
target based on use needs. Do not substitute the publisher's Apple first-token
benchmark for a Windows measurement. Shared-memory audio transport was adopted
after a large-audio immediate-cancellation stress exposed a retained buffer and
blocked queue feeder in the previous serialized-array transport. Keep one
parent-owned mapping per request, and include release behavior in resource
acceptance. Further memory optimizations require measurements of the remaining
capture, validation, resampling, and native buffers.

## Acceptance record template

```text
Date and evaluator:
Machine / Windows build / CPU / RAM / power mode:
App revision / package / model revision:
Microphone / native sample rate:
Settings snapshot (language, dictionary version, cleanup, limits):
Automated suite:
Doctor:
Offscreen smoke:
Live microphone preview:
Application matrix and versions:
Focus/cancel/overflow/timeout trials:
Offline trial:
Dataset version / clip count / total reference words:
Raw and formatted WER by stratum:
Critical-term and number exact match:
P50/P95 startup and stop-to-text:
Peak combined RSS:
Known unsupported cases:
Daily-use decision and follow-up work:
```

Preserve aggregate metrics and necessary settings/version information. Raw
audio/transcripts for an evaluation corpus have their own chosen retention
policy; normal application logging should continue to exclude their contents.
