# Recurrence and motif sidecar

`web/analysis/recurrence.js` turns already-validated structural evidence into a small, deterministic sidecar for an explicitly opted-in choreography strategy. It does not analyze raw audio itself.

The sidecar is intentionally narrow:

- It reads only canonical semantic section IDs/spans plus normalized section energy, optional energy frames, and optional twelve-bin chroma frames.
- It can preserve an existing DSP recurrence group only when every later instance carries the existing strict similarity evidence.
- If chroma and energy frames are available, it can form a new generic repeat identity only with strict tonal, duration, energy, and non-adjacent-time gates.
- It never assigns `verse`, `chorus`, `drop`, genre, lyric, performer, or instrument labels.
- It never creates semantic music events or vehicle/FSEQ commands.

## Contract

Build the semantic timeline first, then capture only allowed evidence and build the sidecar:

```js
const timeline = LightForgeSemanticTimeline.build(music);
const evidence = LightForgeRecurrence.captureEvidence(music, timeline);
const motifs = LightForgeRecurrence.build(timeline, evidence);

if (!LightForgeRecurrence.validate(motifs, timeline, evidence).valid) {
  throw new Error('Do not use an unbound recurrence sidecar');
}
```

`captureEvidence` whitelists `music.sections`, `music.energy`/`energyStep`, and `music.chroma`/`chromaStep`. It copies no labels or lyric-like data. Missing chroma is permitted, but then new recurrence detection is disabled; only a sufficiently evidenced pre-existing DSP repeat relationship can be retained.

The sidecar has both a semantic-timeline fingerprint (using the same FNV-style field pattern as the salience sidecar) and an evidence fingerprint. A timeline, section span, energy value, or chroma value change invalidates it. This is a cache-coherency binding, not a cryptographic authenticity claim.

## Conservative repeat gates

Fresh chroma-and-energy matching requires all of the following:

- sections are separated by at least one second;
- duration ratio is between `0.65` and `1.55`;
- mean normalized energy differs by at most `0.28`;
- all eight time-normalized chroma windows are available; and
- normalized descriptor cosine similarity is at least `0.985`.

These gates intentionally favor missed motifs over false recurrence. Adjacent tonal continuity, a repeated label, or loudness alone cannot create an identity.

## Evolution metadata

Each repeated instance is given only a generic planning hint:

`establish` → `repeat` / `develop` / `escalate` / `release`

The state is calculated from repeat order and bounded energy change. It is not a command and has `requiresChoreographyOptIn: true`. A choreography component may use it to evolve an already-established visual motif, but must validate the sidecar against the exact timeline/evidence and must leave default planning unchanged when no valid sidecar is explicitly supplied.

## Compatibility and limits

No worker, planner, vehicle model, or sequence compiler imports this module automatically. Existing analysis and FSEQ output therefore remain byte-equivalent until a caller deliberately wires a valid sidecar into an opt-in strategy.

Inputs are bounded to 512 sections, 360,000 energy frames, and 72,000 chroma frames. Incomplete, malformed, or stale evidence fails closed instead of being truncated or inferred. The module operates on the decoded-audio clock already established by the semantic timeline.
