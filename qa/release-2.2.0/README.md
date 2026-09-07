# 2.2 background execution evidence

Current release gates are regression-verification.json, browser-verification.json, native-verification.json, analysis-browser-verification.json, analysis-verification.json and android-background-verification.json. All are source-bound and mandatory. The Android gate is produced by the separate CI emulator job; host compilation is not substituted for an Android lifecycle result.

Run `npm test`, `node qa/release-2.2.0/browser.cjs`, `node qa/release-2.2.0/analysis-browser.cjs`, `python3 tests/verify_native_release.py --release 2.2.0` and `python3 tools/verify_retained_analysis.py --from-release 2.1.0`. Model dependencies, licensed reference excerpts and ephemeral CI instrumentation signing are documented in BUILD.md and the workflow. Numeric model evidence is strictly retained from unchanged 2.1 sources; Android background behavior has its own current execution test.
