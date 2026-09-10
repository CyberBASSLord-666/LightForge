# Acoustic vocal semantic enrichment

This optional, offline sidecar makes the existing vocal analysis easier for a
planner to consume without adding a second vocal detector or claiming language
understanding.

## Enable explicitly

Pass `vocalSemanticEnrichment: true` in the existing analysis options. It is
intentionally not a UI default and does not alter the legacy FSEQ path. With
that option absent or false, no `vocalSemantics` or `vocalSemanticLinks` field
is returned, including when a prior opt-in result exists in cache.

## Evidence boundary

`LightForgeVocalSemantics` accepts only accepted `vocals` output with
`sourceSeparated: true`. It consumes the existing:

- phrase boundaries, kind, confidence, intensity and peak;
- GAME/detail note spans and pitch;
- acoustic accent markers (`entrance` and `syllabic-accent`); and
- existing acoustic pitch contour when no accepted note overlaps a phrase.

It adds no audio decode, resample, model inference, text lookup, word, lyric,
phoneme, or speaker identity. `syllableLike: true` means a supplied
`syllabic-accent` acoustic timing marker only. It must never be presented as
linguistic transcription.

## Contract and cache

The sidecar is schema version 1, carries the original decoded-audio clock, and
has a deterministic 64-bit `sourceFingerprint` over only its accepted acoustic inputs.
`validate(sidecar, {duration, vocals})` rejects stale input, corrupt cache,
invalid spans, changed schema, and prohibited linguistic fields.

The worker stores it at the independent `vocal-semantics` checkpoint. A
separation invalidation also removes that checkpoint. The base `bass` checkpoint
explicitly strips `vocalSemantics` and `vocalSemanticLinks`, preventing an
opt-in cache entry from changing a later default analysis result. The sidecar is
rebuilt or restored only after vocal analysis is complete.

Malformed list fields or a validator fault in a persisted `vocal-semantics`
checkpoint fail closed: the worker invalidates that checkpoint and rebuilds it
from the accepted vocal evidence. Cache corruption must not terminate resumed
analysis or introduce words, lyrics, phonemes, or other linguistic content.

`linkTimeline(sidecar, timeline)` returns mappings only when every sidecar
phrase, accepted note, and articulation exactly matches an already-existing
`vocal_phrase`, `vocal_note`, or `vocal_accent` semantic-timeline event on the
same clock. It throws on a mismatch and binds a canonical serialization of the
entire timeline, including salience caps, so any semantic or cap-aware timeline
mutation (including a valid sub-micro numeric change) requires a fresh link.
It first requires the canonical
`LightForgeSemanticTimeline.validate()` check to pass, rather than binding an
otherwise malformed timeline. The link does not mutate the timeline or emit
vehicle commands; any future choreography consumer must opt in separately and
preserve its own collision, density, and vehicle-feasibility gates.

## Limits

This is acoustic expression metadata, not lyrics alignment. Separation bleed,
layered voices, distorted vocals, rapid delivery, and unvoiced consonants remain
ambiguous. The sidecar preserves that uncertainty in confidence and does not
turn low-confidence sound into a primary choreography event.
