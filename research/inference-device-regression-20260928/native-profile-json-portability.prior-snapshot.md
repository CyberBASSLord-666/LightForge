# Native profile JSON portability check

The PR56 CI compiler encountered an enhanced-for loop over Android `org.json.JSONArray`, which does not implement `Iterable`. The calibration test now uses its portable indexed `length()` / `getString(i)` API.

The exact nine-source native-profile CI compilation set and its unchanged `AppDiagnostics` host stub compiled successfully with both Android-first and host-JSON-first dependency orders: 49 classes per order, no compiler diagnostics. All source hashes remained unchanged during compilation. The adjacent JSON receipt is copied byte-for-byte from the successful scratch receipt and records the exact source and dependency hashes.

This receipt describes the source snapshot before subsequent policy and temporal retirement changes. It does not qualify later source changes. Compilation only: no neural inference, APK build, physical-phone performance claim, or release admission.

An earlier attempt to compile all Android sources failed because the scratch harness lacked generated `R.java`; that failed attempt remains in the separate scratch directory `ci-json-portability-01` and is not represented as a pass.
