# Recoverable analysis cache

LightForge keeps private, disposable analysis artifacts in OPFS. They are never
the source for an export and never change the music event, choreography, or FSEQ
produced by a successful fresh analysis. Their only purpose is to avoid repeating
validated work after cancellation, process death, or a later choreography-only
change.

## Identity and cache domains

`web/analysis/work-store.js` exposes `contentAddress(domain, identity)`. It
serializes JSON values canonically (sorted object keys, no non-finite numbers)
before SHA-256 hashing a versioned domain envelope. The same identity therefore
has the same address regardless of JavaScript property insertion order, while a
different domain has a different address.

The current WebView pipeline retains its existing source/settings/runtime
analysis namespace so existing resumable work remains usable. Inside that
namespace its durable stage records are already isolated as `rhythm`,
`separation`, `voice`, `voice-classifier`, `game-*`, and `bass`; source
separation passages (`deux-*`/`mdx-*`) remain independent checkpoint records.
New consumers must use a domain address rather than adding unrelated settings to
the analysis identity. Recommended domains are:

- `decoded-audio`, `shared-features`, `stems`
- `rhythm`, `vocals`, `percussion`, `bass`, `structure`, `semantic-timeline`
- `choreography`, `vehicle-realization`, `fseq`, `validation`

Choreography, UI, and vehicle settings do not belong in an audio/stem identity.
Changing one must not force a stem, rhythm, or vocal recomputation.

## Atomic checkpoints and resume

Each JSON or float checkpoint is written through an OPFS writable stream and is
visible only after `close()`. The record contains its namespace key, stage name,
payload digest, and (for new records) an invalidation generation. A checksum,
swapped-record, truncated-record, non-finite-float, or wrong-generation read is
a cache miss, never a result.

Invalidating dependent stages first commits a small `cache-control` generation
fence. Physical deletion happens only afterwards as storage reclamation. If an
OPFS writer is still locked during cancellation, the old file may remain on disk
but is generation-stale and cannot become a hit on the next resume. A failed
fence write leaves the previous control record and its checkpoints intact.

A missing/corrupt identity discards the namespace before work resumes. A
missing control record migrates a legacy namespace at generation zero; a
corrupt control record discards all non-identity checkpoints because their
invalidation state cannot be proven. `work.diagnostics()` returns a bounded,
privacy-safe recovery summary (control migration/reset, corrupt record count,
fence count, and pending physical deletes). It contains no file path, project
ID, audio payload, or cache key.

## Stem cache integrity

New `stem-cache.js` completion markers are version 2 and include SHA-256 plus
byte length for `vocals.wav`, `accompaniment.wav`, and `voice-full.wav`. The
digest is calculated as output is written; verification reads in 1 MiB chunks,
so validation never allocates an entire long stem at once. A cache restore
verifies both WAV shape and content before the vocal, bass, or structure engine
can consume it. An interior corruption therefore invalidates the separation
result instead of quietly producing false music events.

Version 1 stem markers remain structurally readable for backward compatibility.
They are not falsely described as cryptographically verified; the next stem
rebuild produces a version 2 marker.

## Cancellation and recovery rules

Cancellation retains only persistent analysis identities. The analyzer terminates
the active worker, and the next run uses the same identity to restore completed
stages/passages. A transient, non-fingerprinted audition still discards its
private work on success or failure. A completed separation marker is removed
before any replacement stem stream is opened, so a killed rebuild never exposes
a mixed old/new stem set.

The cache protects correctness and recovery, not a performance claim. Cache hit
cost, streamed integrity verification cost, memory, and wall time must be
measured through the locked benchmark/quality gate before changing defaults or
claiming a speedup.
