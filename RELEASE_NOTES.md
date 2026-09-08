# LightForge 2.2.2 — Troubleshooting logs and renderer recovery

Version code **20202**. **In verification; the signed update is not published yet.** The latest published release remains [2.2.1](https://github.com/CyberBASSLord-666/LightForge/releases/tag/v2.2.1). The 2.2.2 release must pass current-source checks and retain the original signing identity before publication.

## Export a report

Open **Guide → Export diagnostic log** after reproducing a problem. LightForge writes a timestamped `.log` text file to Downloads. If the preview engine has failed, use the reporting action in its native recovery dialog. Reopen the app after a crash before exporting so available Android process-exit information can be included.

The report combines recent app and analysis events, error stacks, worker/renderer failures, timing, app and WebView versions, and memory/storage context. Recent traces are bounded, rotated and retained in private app files across launches. Reports contain no audio, model data or saved-show contents, redact common sensitive values, and are never uploaded automatically. Review the text before posting it publicly.

Android may kill a process without allowing a final log write. The report therefore includes available system exit information and the events saved beforehand; it cannot promise a full stack for every native crash, out-of-memory kill or system failure.

## Renderer recovery

The preview's renderer-loss handler previously assumed its WebView still had a parent. A late callback for a detached view could crash the recovery path itself. Cleanup now checks the parent, handles each WebView once and keeps stale callbacks from clearing a newer preview. The reload dialog waits until the Activity is foregrounded. The service applies corresponding guarded cleanup to its analysis WebView.

Native Studio model quality, background processing and verified completed-passage Resume remain supported. This update does not establish the cause of every phone crash or the manufacturer “clear cache” message; the exported report supplies the device evidence needed for the next diagnosis.

## Validation and update compatibility

Current 2.2.2 regression, diagnostic-export, browser, Android and package verification are pending. Historical 2.2.1 performance and lifecycle evidence is preserved separately and is not represented as a new 2.2.2 measurement. See [VALIDATION.md](VALIDATION.md) for current status and scope.

Once published, install the complete **LightForge-2.2.2.apk** over the existing app **without uninstalling**. The release gate must verify the original signing certificate, current version, all bundled assets and checksum. Physical-phone and Tesla validation remain outstanding. Existing model-license restrictions remain in effect.

Earlier features and release history are retained in [CHANGELOG.md](CHANGELOG.md).
