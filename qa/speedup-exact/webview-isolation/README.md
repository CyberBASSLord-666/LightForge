# Shared-memory WebView qualification — pending

The candidate enables shared-memory WebAssembly using the public
AndroidX WebKit 1.18.0-alpha01 API. It does not change ONNX weights, numerical
precision, passage geometry, GAME seeds, or its eight diffusion steps. Actual
runtime capability and raw model-output equality remain separate required checks.

`WebViewIsolation.configure` runs before the first load in both MainActivity and
AnalysisService. It detects `MULTI_PROFILE` and
`CROSS_ORIGIN_ISOLATED_ALLOWLIST`, reads the WebView's existing profile, and grants
only `https://appassets.androidplatform.net`. It never selects a different profile.
The shared intercepted-response transport supplies
`Document-Isolation-Policy: isolate-and-credentialless` to documents and workers.
Existing COOP, COEP, CORP, MIME, range and cache policies remain present. Android requests only one or four threads, and four requires at least eight reported cores. Beat recognition and voice classification remain serial because their raw outputs changed in the all-four-thread experiment. The candidate retires classification before loading a separate GAME worker; its complete replay is still pending. Resource
and navigation checks use the same exact scheme/authority predicate. Provider
support or setup failure is logged; the worker still requires actual isolation
and SharedArrayBuffer before it requests multiple threads.

The supplied September 8–9 diagnostic snapshots reported an eight-core arm64
Samsung SM-F976U1, WebView 154.0.8037.0 and 11,623,878,656 bytes total RAM. Available
RAM ranged from 1,901,707,264 to 2,935,578,624 bytes in those snapshots. They were
from app 2.2.2 and are historical observations, not a measurement of current free
memory. This is why a second GAME model heap, which needs 6 GiB freshly available
under the current conservative admission rule, is not the primary speed route.

Evidence is deliberately separated:

- `transport-verification.json` executes the production Java response/header and
  Chromium-style range contract: 274 checks, 33 exact responses and 23,161,377
  compared bytes. It does not establish Android isolation or model performance.
- The earlier stock WebView 124 capability probe is retained in `../android-cpu`.
  It lacked shared memory with COOP/COEP alone. That result does not describe the
  new public API or the user's newer provider. Production activation of the two-heap GAME pool is now explicitly disabled.
- `../game-threads-controlled.json` is a controlled local x86 WASM experiment.
  Its 2.78× median 1-to-4-thread gain applies only to the measured GAME graph
  execution. It is not an Android or complete-track speed claim.
- Full public-pipeline raw 1-to-4-thread comparison and an actual modern Android
  provider run are pending. A setter return value, matching browser version,
  rounded-note agreement, or desktop identity model cannot substitute for them.

Official references:

- [AndroidX release](https://developer.android.com/jetpack/androidx/releases/webkit#1.18.0-alpha01)
- [Profile allowlist API](https://developer.android.com/reference/androidx/webkit/Profile#setCrossOriginIsolatedAllowlist(java.util.Set))
- [Official intercepted-document and worker tests](https://android.googlesource.com/platform/frameworks/support/+/androidx-main/webkit/integration-tests/instrumentation/src/androidTest/java/androidx/webkit/WebViewCrossOriginIsolatedAllowlistTest.kt)
- [Chromium 154 feature default](https://chromium.googlesource.com/chromium/src/+/154.0.8037.0/android_webview/common/aw_features.cc#116)

No complete-track speedup or physical-device execution is claimed here.
