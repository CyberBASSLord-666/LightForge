# Native audio and persisted-project repair verification

The production audio importer and project store were compiled on the host against the Android API declarations, with a real host `org.json` implementation. `verification.json` records the exact source hashes and results.

## Changes

- Existing projects validate their canonical playback WAV and disposable 22.05 kHz mono analysis copy before the local server opens analysis audio. Missing, truncated, malformed or duration-mismatched analysis is rebuilt from the intact playback WAV using temporary files and atomic replacement. Good analysis is not rewritten. Playback samples and editable settings remain unchanged; cancellation preserves the prior file and removes temporary outputs.
- The native WAV reader explicitly rejects data ending mid-frame instead of dropping a partial sample. Sixty input variants cover PCM8/16/24/32, float32, mono/stereo, rates 8–384 kHz, extensible headers, odd metadata padding and non-round sample counts.
- Decoded PCM reads use the actual output encoding/channel count, respect buffer offset/size, retain partial frames across decoder output buffers and reject an incomplete final frame. Fifteen adversarial chunk cases compare entire-buffer conversion against 137-byte fragments for mono/stereo/5.1 and all five supported PCM encodings.
- Multichannel downmix retains all source channels, honors positional channel masks, and reserves headroom. Thirty-three solo-channel cases plus two explicit masks check that quad and surround channels are not silently dropped.
- `ProjectStoreTest` and the native resampler/PCM preservation tests were rerun against these production sources. The audio-only run of `NativeAudioTest` does not claim FSEQ validation; the release's separate sequence checks cover that step.

## Common compressed music support

The app uses Android `MediaExtractor` and `MediaCodec` to decode unprotected MP3, AAC in M4A/MP4 or ADTS AAC, FLAC, Ogg Vorbis/Opus, and compatible WebM/Matroska audio tracks. The picker accepts the common audio MIME types and mislabeled providers. Container recognition is based on the file data, not renaming its extension. Actual codec/container availability remains a property of the device. AAC ADIF and DRM music are excluded; M4A files with an unsupported codec such as ALAC are not implied by AAC-in-M4A support.

The compressed codec itself was **not executed in the host JVM**: Android SDK jars contain framework stubs. These checks establish the actual native PCM conversion, storage and decoder-output handling; they do not pretend to be device MP3/AAC/FLAC/Opus end-to-end tests.

Primary references:

- Android supported media formats: https://developer.android.com/media/platform/supported-formats
- Android MediaCodec API: https://developer.android.com/reference/android/media/MediaCodec
- Android codec compatibility test for advisory float PCM output requests: https://android.googlesource.com/platform/cts/+/refs/heads/android10-release/tests/tests/media/src/android/media/cts/MediaCodecTest.java

## Re-run

From `app/lightforge`, with the build toolchain already bootstrapped and the host test JSON jar available:

```bash
../toolchain/jdk17/bin/javac --release 8 -cp ../toolchain/test-json.jar:../toolchain/android-sdk/platforms/android-35/android.jar:build/classes -d qa/audio-audit/classes android/src/com/cyberbasslord/lightforge/WavConverter.java android/src/com/cyberbasslord/lightforge/AudioImporter.java android/src/com/cyberbasslord/lightforge/ProjectStore.java qa/audio-audit/ImportAuditTest.java qa/audio-audit/RepairAuditTest.java tests/ProjectStoreTest.java tests/NativeAudioTest.java
../toolchain/jdk17/bin/java -cp qa/audio-audit/classes:../toolchain/test-json.jar:../toolchain/android-sdk/platforms/android-35/android.jar com.cyberbasslord.lightforge.ImportAuditTest qa/audio-audit/results
../toolchain/jdk17/bin/java -cp qa/audio-audit/classes:../toolchain/test-json.jar:../toolchain/android-sdk/platforms/android-35/android.jar com.cyberbasslord.lightforge.RepairAuditTest qa/audio-audit/repair-results
../toolchain/jdk17/bin/java -cp qa/audio-audit/classes:../toolchain/test-json.jar:../toolchain/android-sdk/platforms/android-35/android.jar com.cyberbasslord.lightforge.ProjectStoreTest qa/audio-audit/projectstore-results
../toolchain/jdk17/bin/java -cp qa/audio-audit/classes:../toolchain/test-json.jar:../toolchain/android-sdk/platforms/android-35/android.jar:build/classes com.cyberbasslord.lightforge.NativeAudioTest qa/audio-audit/native-results
```

Generated `classes` and `*-results` directories are temporary host fixtures and need not be included in the source backup.
