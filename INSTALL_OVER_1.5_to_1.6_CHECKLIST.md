# LightForge — install-over 1.5.0 → 1.6.0 checklist

Mirrored from LF Platform shared notes for Lead / QA. Owner remains **LF Platform**; Docs keeps this copy in-repo for discoverability.

Related: [`BUILD.md`](BUILD.md) (signing continuity / `adb install -r`), [`VALIDATION.md`](VALIDATION.md), [`VERSIONING.md`](VERSIONING.md) (when landed).

---


**Owner:** LF Platform  
**Audience:** LightForge Lead / LF QA  
**Scope:** Package identity, API 26–35, WebView, permissions, OEM quirks  
**Verified against:** `LightForge-1.5.0.apk` dump (`versionCode=10500`) + 1.6.0 private source (`versionCode=10600`, targetSdk 35)

---

## Confirmed package delta (no surprise gates)

| Field | 1.5.0 | 1.6.0 | Install-over impact |
|-------|-------|-------|---------------------|
| package | `com.cyberbasslord.lightforge` | same | Must match |
| versionCode | `10500` | `10600` | Must increase (OK) |
| versionName | `1.5.0` | `1.6.0` | Cosmetic |
| minSdk | 26 | 26 | Unchanged |
| targetSdk / compileSdk | 35 | 35 | Unchanged — no new targetSdk policy cliff |
| uses-permission | none | none | Unchanged — SAF only |
| signing cert SHA-256 | `7187d6aa…016c6b` | same identity required | Mismatch = INSTALL_FAILED_UPDATE_INCOMPATIBLE |
| signature schemes | v2+v3 (v1 false) | v2+v3 | OK for API 26+ |

**Hard rule:** Install over existing app. Do **not** uninstall first (projects live in app-private storage). Prefer `adb install -r LightForge-1.6.0.apk`.

---

## Pre-install gates (block QA device work if any fail)

- [ ] APK package name is `com.cyberbasslord.lightforge`
- [ ] `versionCode` is `10600` (> installed `10500`)
- [ ] Cert SHA-256 matches known release identity:  
      `71:87:D6:AA:93:5D:5B:7D:2D:65:6C:B8:79:13:AF:95:FE:1C:A3:A4:B1:65:30:36:D1:D8:D8:90:E2:01:6C:6B`
- [ ] `apksigner verify` shows v2+v3 verified
- [ ] Device API ≥ 26; skip / mark N/A below 26
- [ ] Existing install is the private-signed 1.5.0 (not a debug/self-signed rebuild)

If signing identity differs: stop — uninstall/reinstall loses projects; escalate to Lead + LF Security (do not regenerate keystore).

---

## API matrix (26–35) — what to exercise

Both builds already target 35 / min 26, so this is **runtime + WebView provider** coverage, not a new manifest cliff.

| API | Typical OS | Focus |
|-----|------------|--------|
| 26–28 | Oreo / Pie | Baseline WebView; no gesture nav edge cases; confirm SAF persistable grants survive update |
| 29 | Q | Scoped storage already N/A (no legacy storage perms); SAF pickers |
| 30–32 | R / S | `WindowInsets` path in MainActivity (`SDK_INT>=30`); cutout/IME padding; gesture nav |
| 33 | T | Predictive back disabled in manifest (`enableOnBackInvokedCallback=false`) — confirm custom `onBackPressed` / JS `handleNativeBack` still works |
| 34–35 | U / V | Same targetSdk 35 posture; confirm no OEM “restricted settings” / installer blocks for sideload update |

**Device-side smoke after `-r` install (every API band):**

1. App launches to studio (no blank WebView / crash dialog)
2. Existing 1.5 projects still listed; open one without re-import
3. SAF: pick audio + restore show ZIP still works (persistable URI)
4. Export / share still grants read URI
5. Preview audio plays (media gesture disabled in WebSettings — autoplay path)
6. Rotate / fold (if applicable): UI retained via `configChanges`
7. Process death / “Reload the studio” path if WebView renderer dies — projects still on device

**Post-update product note (not a platform blocker):** existing 1.4/1.5 shows reopen with prior frame payload; user may need **Analyze voice detail** / **Re-analyze music** once for 1.6 vocal path. Cached listening layers may need regen after storage cleanup.

---

## Permissions posture

- Manifest declares **no** dangerous permissions (confirmed aapt badging / manifest).
- File access is **SAF** (`ACTION_OPEN_DOCUMENT`) + persistable URI grants + app-private files.
- Share uses `FLAG_GRANT_READ_URI_PERMISSION` + ClipData.
- `allowBackup=false`, `usesCleartextTraffic=false`, `largeHeap=true`.

**QA checks:**

- [ ] No unexpected runtime permission prompts on first launch after update
- [ ] Previously granted SAF folders/files still readable after install-over
- [ ] Revoking a document grant in system Settings → app fails that URI gracefully (no crash)
- [ ] OEM “Permission manager” / “Special app access” shows nothing unexpected for LightForge

If an OEM invents a prompt for “files” or “all files”: that is OEM overlay — capture screenshot + `adb shell dumpsys package com.cyberbasslord.lightforge` and ping Platform (do not chase `MANAGE_EXTERNAL_STORAGE`; app does not declare it).

---

## WebView checklist (critical path)

App UI is WebView-hosted from `https://appassets.androidplatform.net` with request interception (`WebViewFileTransport`). Settings: JS on, DOM storage on, file/content access **off**, mixed content **never**, no multi-window, media playback **without** user gesture, textZoom 100.

| Check | Pass criteria | Fail signal |
|-------|---------------|-------------|
| Provider present | System WebView / Chrome provider enabled | Blank screen, `WebView` factory crash |
| Origin load | `index.html` via appassets origin | Infinite load / white screen |
| Intercept / range | Audio seek & large asset streaming | Truncated audio, 416/range errors in logcat |
| COOP/COEP isolation headers | Shared WASM memory path for analysis | Analysis worker fails; check transport headers |
| Renderer crash recovery | Dialog → Reload; projects intact | Lost projects (should not happen) |
| OEM WebView pin | Update Android System WebView / Chrome if provider ancient | Crashes on API 26–28 OEMs with stale WebView |

**logcat filters for QA/Platform:** `chromium`, `WebView`, `lightforge`, `AndroidRuntime`.

**OEM WebView quirks to watch:**

- Samsung / Xiaomi / Oppo / Vivo / Huawei(GMS): outdated WebView after OS update — force WebView update before blaming APK
- Android Go / low-RAM: `largeHeap` helps but OOM during neural analysis is possible — capture meminfo, not install failure
- Custom ROMs blocking `JavascriptInterface` — Bridge would break; rare

---

## OEM / sideload install-over quirks

| Symptom | Likely cause | Platform action |
|---------|--------------|-----------------|
| `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | Different signing key | Stop; restore private signing identity — never “fix” with uninstall unless user accepts data loss |
| `INSTALL_FAILED_VERSION_DOWNGRADE` | Installing older APK | Confirm APK is 10600 |
| `INSTALL_FAILED_USER_RESTRICTED` / blocked by MIUI | OEM installer / USB install toggle | Enable “Install via USB” / disable MIUI optimization as last resort; document OEM |
| Play Protect / “blocked” | Sideload heuristic | User allow once; cert is private personal — expected |
| Success but icon missing / old icon | Launcher cache | Reboot or clear launcher cache; package still updated |
| Success, cold start crash | WebView / ABI / dex | Collect tombstone + `adb bugreport`; Platform triage |
| Success, projects empty | User uninstalled first **or** different user profile / work profile | Confirm same Android user + no uninstall |
| Dual apps / clone | Clone has separate data | Test on primary profile only |
| Work profile | Separate package install | Install into same profile that has 1.5.0 |

**Samsung:** Secure Folder / dual messenger clones — treat as separate installs.  
**Xiaomi/Redmi:** Autostart + battery restrictions can kill long analysis — not install failure; note for Performance if needed.  
**Huawei (no GMS):** WebView channel differs — confirm WebView package updates independently.

---

## QA failure support (Platform on-call)

When install fails, QA should send:

1. Exact `adb install -r` output (or installer UI screenshot)
2. Device: model, Android version / API, security patch
3. Pre-state: `adb shell dumpsys package com.cyberbasslord.lightforge | head` (versionCode, signatures, userId)
4. Cert of candidate APK vs known SHA-256 above
5. Whether 1.5.0 was uninstalled

Platform triage order: **signature → versionCode → package name → OEM policy → WebView post-launch**.

Standing by for QA install failures; report findings to Lead.

---

## Report line for Lead

**LF Platform: install-over 1.5.0→1.6.0 is low-risk on package policy — same package, min/target 26/35, no new permissions, versionCode 10500→10600, same private signing identity required. Checklist covers API 26–35 smoke, SAF grant survival, WebView provider/OEM quirks, and failure triage. Ready to support QA if any install fails.**
