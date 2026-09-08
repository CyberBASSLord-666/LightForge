# LightForge 2.2.2 — Troubleshooting logs and renderer recovery

Version code **20202**. This signed update retains the original LightForge signing identity and passes all seven release gates. Install **LightForge-2.2.2.apk** over the existing app **without uninstalling**.

## Export a report

Open **Guide → Export diagnostic log** after reproducing a problem. On Android 10+, LightForge writes a timestamped `.txt` log file to **Downloads/LightForge**. On Android 8–9, choose Downloads in the system save dialog. If the preview engine has failed, use the reporting action in its native recovery dialog. Reopen the app after a crash before exporting so available Android process-exit information can be included.

The report combines recent app and analysis events, error stacks, worker/renderer failures, timing, app and WebView versions, and memory/storage context. Recent traces are bounded, rotated and retained in private app files across launches. Reports contain no audio, model data or saved-show contents, redact common sensitive values, and are never uploaded automatically. Review the text before posting it publicly.

Android may kill a process without allowing a final log write. The report therefore includes available system exit information and the events saved beforehand; it cannot promise a full stack for every native crash, out-of-memory kill or system failure.

## Renderer recovery

The preview's renderer-loss handler previously assumed its WebView still had a parent. A late callback for a detached view could crash the recovery path itself. Cleanup now checks the parent, handles each WebView once and keeps stale callbacks from clearing a newer preview. The reload dialog waits until the Activity is foregrounded. The service applies corresponding guarded cleanup to its analysis WebView.

Native Studio model quality, background processing and verified completed-passage Resume remain supported. This update does not establish the cause of every phone crash or the manufacturer “clear cache” message; the exported report supplies the device evidence needed for the next diagnosis.

## Validation and update compatibility

All seven source-bound release gates pass: regression, browser UI, native compilation/storage, the actual public model pipeline, numerical kernel evidence, Android background lifecycle and Android diagnostic export. Current regressions pass **155 Node tests and 54 Python tests**, with **22 native host checks**. The complete [production verification run, attempt 2](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34179649874/attempts/2) passed; [VALIDATION.md](VALIDATION.md) records evidence provenance and test limits.

Android 15 testing verifies a real uncaught exception and process restart, retained sanitized stacks, unique readable `.txt` exports in Downloads, the real Guide action, and reporting after detached/stale renderer callbacks. Native Studio also completes with the screen off and reuses a saved passage after Cancel/Resume. The selected-document helper returns the provider's actual filename; legacy Android picker UI remains untested.

Numerical model/kernel evidence is retained only after exact source/model verification and a fixed review of the diagnostics adapter changes. The source-clock regression is fresh. The 2.2.1 neural accuracy and host performance measurements remain historical; current complete-browser and Android execution are tested separately.

The complete update is **1,171,745,041 bytes**, SHA-256 `4327295e32b369861d1689686cc877c88f5131402c3ad958e0f93bf5d0a10ebf`. Original certificate, version, bundled assets and native-library checks pass. Physical-phone and Tesla validation remain outstanding. This update does not claim that every phone crash or manufacturer cache warning is resolved. Existing model-license restrictions remain in effect.

Earlier features and release history are retained in [CHANGELOG.md](CHANGELOG.md).
