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

## Analysis-worker opt-in and cache boundary

`MusicAnalyzer.analyze()` schedules a final `recurrence` worker stage only when its caller supplies:

```js
{ recurrenceAnalysis: true }
```

That stage runs after the completed rhythm, separation, voice, and bass stages. It does not decode audio, invoke a model, create a stem, or modify the approved rhythm map. It validates the current canonical semantic timeline, captures the whitelisted structural evidence, then validates both the evidence and resulting sidecar before exposing them as:

```js
analysis.recurrenceAnalysis // explicit provenance marker
analysis.recurrenceEvidence
analysis.recurrenceSidecar
```

`recurrenceAnalysis` has `enabled: true`, the `recurrence` cache-domain name, engine/schema versions, and the exact timeline/evidence fingerprints. It is deterministic: it does not disclose whether the record was restored or recomputed.

The worker stores its record only in the distinct `recurrence` cache domain. A cache hit is accepted only when `validateEvidence()` and `validate()` bind it to the current timeline. A changed section, energy/chroma feature, timeline cap, or audio-clock validation failure invalidates the record and rebuilds it from canonical evidence. The normal bass checkpoint deliberately strips all three recurrence fields, so a choreography-only opt-in never makes source separation, vocal analysis, or bass tracking run again. Default callers do not schedule this stage and receive no recurrence fields.

## Exact choreography dependency

Motif evolution is not enabled merely because recurrence metadata exists. It may activate only when all of the following are true:

1. analysis was explicitly run with `recurrenceAnalysis: true`, proven by a current valid `analysis.recurrenceAnalysis.enabled === true` marker and a sidecar that validates against the supplied timeline/evidence;
2. choreography explicitly requests `semanticChoreography: true`; and
3. choreography explicitly requests `motifEvolution: true`.

If any one condition is absent, stale, wrong-clock, or invalid, the motif strategy must report an inactive reason and preserve the legacy choreography path. Hand-supplied sidecars are subject to the same marker and exact-binding checks; there is no implicit activation path.

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

The analysis worker loads the module only for the explicit recurrence stage. The normal pipeline neither schedules that stage nor returns a sidecar unless `recurrenceAnalysis: true` is explicit. A valid sidecar still has no effect on the planner, vehicle model, or sequence compiler unless the three-part choreography dependency above is also explicit. Existing default analysis and FSEQ output therefore remain byte-equivalent.

Inputs are bounded to 512 sections, 360,000 energy frames, and 72,000 chroma frames. Incomplete, malformed, or stale evidence fails closed instead of being truncated or inferred. The module operates on the decoded-audio clock already established by the semantic timeline.
