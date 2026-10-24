# Host project JSON support

The Java files named in `provenance.json` are unmodified Apache-2.0 AOSP sources
from `platform/frameworks/base` at commit
`cc8bb19595c661f5cf42f330457000e643c67d1b` (Android 15 release branch).
Each file retains its upstream license header. The manifest records the exact
source URL and SHA-256; the host helper verifies each digest before compilation.
`RavenwoodKeepWholeClass` is only a compile-time annotation stand-in and contains
no parser logic. Production imports the device's built-in `android.util.JsonReader`.

The SDK `android.jar` contains non-executable stubs. Host storage tests therefore
compile this actual platform parser into a **separate** host-support directory,
then prepend it to the host JVM classpath. Never copy these classes into
`native-classes`, instrumentation, an APK, or a production dependency. The
native release verifier records their source hashes and uses them only at host
execution time. Existing export-session host tests compile ProjectStore but do
not execute it; they do not require parser support at runtime.

Run ordinary storage checks with:

    python3 tests/test_project_json_validation.py

This separately compiles and exercises unchanged production sources (depth 64)
and a temporary test-only ProjectStore copy whose sole change is the checked,
single constant replacement from 64 to 4. The latter verifies a four-container
project and its five-container saved-revision envelope through save, undo, and
recovery. It is explicitly not byte-identical production execution. All JSON
fixtures are small; these tests do not reproduce a crash or run stress payloads.
The existing ProjectStoreTest also runs in both configurations.

`tests/verify_native_release.py` executes ProjectStoreTest, NativeRecoveryTest,
AnalysisJobStoreTest, AnalysisRendererRecoveryTest, and ProjectJsonValidationTest
with this support. A manually compiled `ExportRestoreTest` must use the same
host runtime classpath prefix: `qa/release-<version>/project-json-host-classes`
before `qa/release-<version>/native-classes`, followed by the existing JSON,
Android SDK, and native-runtime test dependencies. Compile it against the
ordinary production classes, not the host support. Device instrumentation uses
the platform parser directly and needs no extra classpath.

The preflight uses Android's strict **mode** (`setLenient(false)`), not a custom
quote scanner. It counts object/array nesting before recursive JSONObject
parsing, rejects extra top-level content, and retains existing byte bounds.
This is not a claim of complete RFC JSON conformance: Android's own reader has
historically permissive string escape behavior. Host execution with these
pinned platform sources also does not establish Android device behavior;
real-device instrumentation remains a separate validation step.
