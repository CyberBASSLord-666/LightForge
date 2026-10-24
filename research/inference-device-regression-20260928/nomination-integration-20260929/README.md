# Screening correction: original-model integration

The current screening-memory correction passes the original-model host integration
on September 29, 2026. Both JNI processes exit successfully. All seven complete
outputs are finite and byte-identical to the committed original demo output:
`d9cd80a15c19921b2f472233a4a3bb86eec3e39aef66374a9c007b4b9efc5837`.
Each contains 1,146,600 Float32 values (4,586,400 bytes).

The checks cover baseline, unknown/short-work admission, four-worker and
eight-worker execution, an actual automatic first pair, legacy-cache rejection,
and exact recovery. Three concurrent native cancellation modes and synchronous
baseline cancellation observe active JNI execution, exclusive gate ownership,
complete worker retirement, cleanup and recovery. The interrupted owner retains
its flag. No partial output is committed. The graph inventory stays at 27 original
graphs, with 335 baseline or 1,727 candidate calls.

`receipt.json`, compile/process logs and frozen source snapshots are exact copies
of the successful run. `archive.json` independently checks their retained bytes,
all compiled-class hashes, current source bindings, and all seven actual output
files before omitting the audio, PCM, class and model binaries from this archive.
The production NativeDeux source SHA-256 is
`a5f798a19afc160407b0f1d06960a55120692a359bf9f7a4d3c5a28f471c1751`.

These are host correctness and retirement checks. They are not controlled speed
measurements, phone qualification, sustained whole-job benefit, or production
release approval. The installed version 2 companion predates this source change.

Command:
```sh
python3 tools/verify_deux_passage.py --mode integration --output /dev/shm/lightforge-nomination-integration-20260929-01
```
