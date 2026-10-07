# Typed reusable rhythm features

This development tranche adds an explicit contract to the existing rhythm DSP
cache. It does not add a universal frontend broker, a detector, concurrent model
execution, or a performance claim. The heavy scheduler still admits one pipeline.

## Identity and compatibility

`LightForgeFeatureStore.normalizeTransform` validates version 1 Float32 packed
feature descriptors. Its source role and SHA-256, analysis sample rate and global
clock origin, frontend identifier and configuration digest, storage/arithmetic
precision, packed shape, and ordered component geometries participate in the
content address. Every component names its shape, frame origin, hop, window and
padding. Unknown fields, duplicate components, incompatible dtype, inconsistent
shape and oversized payloads are rejected. This first contract intentionally
supports one packed Float32 tensor; it does not silently generalize to other
precision or frontend families.

Rhythm and recurrence both construct the same descriptor from the existing DSP
configuration and duration. The clock is the original song clock, with no latency
subtraction. Spectral components use the existing symmetric Hann window; RMS is
rectangular. Fine RMS records fractional quarter-hop spacing and its rounded
integer boundaries, rather than inventing a fixed 110-sample window. Chroma records
the existing ten-frame sum divided by ten, including the final partial block.
Window samples for this aggregate describe each constituent spectral window.
Configuration hashing also binds resampling FIR, bands and other frontend inputs.
JavaScript arithmetic remains binary64 with existing Float32 intermediate/output
rounding; the frontend version captures that algorithm. No DSP loop changes.

Legacy callers without a transform keep their existing identity schema and key.
Typed callers use a new content address and do not reinterpret unspecified legacy
features. A cache miss rebuilds the same DSP output; saved analyses and projects
are not migrated or recomposed by this change. Typed Float32 descriptors must
match the caller's expected transform before the binary payload is read. Existing
checksums, invalidation fences and binary-first/descriptor-last publication stay
in force. This protects compatibility and accidental corruption, not hostile
same-origin code capable of rewriting the entire store.

## Resource scope

The feature Float32 payload ceiling is 16 MiB minus 4,100 bytes, matching the
existing work-store write ceiling. Typed rhythm identity construction checks it
before allocating a packed copy, so long tracks bypass reusable-feature caching
and continue normal analysis. Direct writes reject excessive payloads before
invalidating a previous record. Reads reject excessive declared lengths before
loading their binary payload. This is a per-record cache limit, not a process
memory cap or a new admission policy.

Work-store observations now count Float32 binary read allocations, decoded array
allocations and copies, and encoded write allocations/copies. Worker observations
also count rhythm packing and the beat/downbeat arrays allocated on cache hits.
Observers cannot alter storage success. These are cumulative, partial
instrumentation counters; they do not measure live memory, garbage collection,
model heaps or process peak memory, and cannot justify raising scheduler capacity.

## Verification

`tests/feature-store-contract.test.cjs` checks transform isolation, legacy misses,
shape/precision/source rejection, rechecksummed descriptor corruption, interrupted
publication and successful resume, bounds before replacement, observer failure,
and actual DSP extraction/cache/recurrence reuse. Fresh and restored buffers are
byte-identical and their DSP summaries are equal. Capacity-one scheduler and
resource diagnostic tests remain part of the focused run. These host tests do
not qualify original models, browser IPC, Android lifecycle or physical devices.
