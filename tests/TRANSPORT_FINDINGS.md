# Android audio transport regression

The v1.0.0 intercepted file response sought to the requested byte offset before
returning its Java `InputStream`. Chromium's Android WebView stream loader then
parsed the original `Range` request and sought forward by that offset again.
For the first PCM request beginning at byte 44, the returned body was 44 bytes
short. The worker's strict PCM length check consequently reported “Audio data
ended unexpectedly.” The same transport also served the audio preview.

The corrected production transport returns a stream positioned at the beginning
of the file, bounded at the requested final byte. Chromium performs the starting
seek once. The response still supplies the actual partial Content-Length and
Content-Range. It supports all Java read overloads, EOF, zero-length reads,
bounded availability and skip, and closes the underlying file. Responses are
not stored in browser cache. Range syntax and unsatisfiable bounds are checked.

For files above 2 GiB, Chromium's signed 32-bit length estimate could produce
conflicting Content-Length headers. The app uses the existing 22.05 kHz mono
analysis WAV as an explicitly labeled long-track preview. Canonical stereo
audio remains unchanged for native export. Direct WebView requests for an
oversized original return 413 instead of a malformed stream response.
`ProjectPreviewTest.java` checks selection at the exact integer boundary and
the four-hour size, and preservation of original URLs and file bytes.

This is established by these primary source implementations:

- [AndroidStreamReaderURLLoader: ParseRange and OnInputStreamOpened](https://chromium.googlesource.com/chromium/src/+/main/components/embedder_support/android/util/android_stream_reader_url_loader.cc)
- [InputStreamReader: VerifyRequestedRange and SkipToRequestedRange](https://chromium.googlesource.com/chromium/src/+/main/components/embedder_support/android/util/input_stream_reader.cc)
- [InputStream: Java read/skip JNI calls](https://chromium.googlesource.com/chromium/src/+/main/components/embedder_support/android/util/input_stream.cc)
- [InputStreamUtil: direct Java stream method dispatch](https://chromium.googlesource.com/chromium/src/+/main/components/embedder_support/android/java/src/org/chromium/components/embedder_support/util/InputStreamUtil.java)

The initially considered FilterInputStream double-decrement hypothesis was
rejected: the inspected Android 7, Android 14 and current AOSP implementations
directly delegate the three-argument read method to the wrapped stream.

`WebViewTransportTest.java` executes the actual production helper with a
source-based adapter for Chromium's availability, range, seek and read sequence.
It first reproduces the old 44-byte deficit, then verifies 135 byte-exact
responses over 107,921,458 compared bytes. Coverage includes the original full
Glass Castle audio, the demo, overlapping analysis chunks, out-of-order playback
seeks, suffix/open ranges, malformed ranges, empty files, Java stream contracts,
and protected handling of a sparse four-hour PCM file above 2 GiB. All 841 checks pass.
The machine-readable receipt is `transport-verification.json`.

`WebViewTransportServer.java` exposes that same production transport and Chromium
adapter through a localhost HTTP server so the actual browser analysis worker
can consume the resulting responses. This adapter and the host tests do not
constitute an actual Android device/WebView runtime test.

To compile from the extracted private source workspace after toolchain bootstrap:

```sh
mkdir -p app/lightforge/tests/transport-classes
app/toolchain/jdk17/bin/javac --release 8 -d app/lightforge/tests/transport-classes app/lightforge/android/src/com/cyberbasslord/lightforge/WebViewFileTransport.java app/lightforge/tests/WebViewTransportTest.java app/lightforge/tests/WebViewTransportServer.java
```

Pass one or more canonical WAV fixtures to `WebViewTransportTest`: the first
argument is the first WAV, the second is a temporary directory, and subsequent
arguments are additional WAV files. The original deficit check expects the first
fixture to contain at least 441,044 bytes.
