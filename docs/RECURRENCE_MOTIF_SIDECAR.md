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

MusicAnalyzer schedules a final recurrence worker stage only when its caller
explicitly supplies `{ recurrenceAnalysis: true }`.

That stage runs after completed rhythm, separation, voice, and bass work. It
does not decode audio, invoke a model, create a stem, or modify the approved
rhythm map. It validates the current canonical semantic timeline, captures the
whitelisted structural evidence, then validates both the evidence and sidecar
before exposing an explicit provenance marker plus the evidence and sidecar:

```js
analysis.recurrenceAnalysis
analysis.recurrenceEvidence
analysis.recurrenceSidecar
```

The recurrence marker contains `enabled: true`, the `recurrence` cache
domain, version fields, and exact timeline/evidence fingerprints. The distinct
cache record is accepted only when both validators bind it to the current
timeline. A changed section, energy/chroma feature, salience cap, or
audio-clock validation failure invalidates it and rebuilds from canonical
evidence. The normal bass checkpoint strips all three recurrence fields, so
this choreography-only opt-in never reruns source separation, voice analysis,
or bass tracking. Default callers schedule no recurrence stage and receive no
recurrence fields.

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

The normal pipeline neither schedules the recurrence stage nor returns a
sidecar unless `recurrenceAnalysis: true` is explicit. A valid sidecar still
has no effect on the planner, vehicle model, or sequence compiler unless the
three-part choreography dependency below is also explicit. Existing engine-default
analysis and FSEQ output therefore remain byte-equivalent.

Inputs are bounded to 512 sections, 360,000 energy frames, and 72,000 chroma frames. Incomplete, malformed, or stale evidence fails closed instead of being truncated or inferred. The module operates on the decoded-audio clock already established by the semantic timeline.

## Opt-in choreography consumption

The sidecar remains data unless every one of these independent proofs holds:

- the caller supplies the exact \`semanticTimeline\`, \`musicSalience\`,
  \`recurrenceEvidence\`, and \`recurrenceSidecar\`;
- the semantic timeline and salience sidecar activate a real linkable semantic
  strategy for the current planner targets;
- \`LightForgeRecurrence.validate(recurrenceSidecar, semanticTimeline,
  recurrenceEvidence)\` succeeds; and
- the analysis result contains an exact \`recurrenceAnalysis\` provenance marker
  with \`enabled: true\`, while settings explicitly set both
  \`semanticChoreography: true\` and \`motifEvolution: true\`.

\`web/engine/motif-evolution.js\` is the narrow bridge used by the show engine.
It never calls \`captureEvidence\` or \`build\`; missing, corrupt, stale,
oversized, span-incompatible, or semantically inactive input is inactive and
leaves the corresponding non-motif composition unchanged. A real base semantic
composition must become active before motif scenes are considered. If a later
motif composition becomes inactive or faults, the validated base semantic plan
is retained; if the base semantic plan cannot activate, legacy planning is
retained. For a validated assignment it carries the generic motif identity into
the section scene and maps bounded \`phase\`, \`repetitionIndex\`,
\`variation\`, and energy context to a deterministic per-instance seed/variant
plus at most a 0.12 intensity change. It does not apply command-timing offsets,
add musical events, overwrite a user-supplied section seed, or relax
vehicle/collision checks.

## Studio defaults since 2.3.0

The worker and engine APIs retain their explicit opt-in contracts. New Studio
projects set `recurrenceAnalysis`, `semanticChoreography` and `motifEvolution`
to true through **Follow musical expression**. Saved projects with absent or
false flags retain their existing composition until the user enables it.

Enabling expression on a completed version-8 analysis validates and reuses
current recurrence evidence and its sidecar when available. This preserves
chroma retained only inside the evidence receipt across off/on changes. If
there is no current receipt, the app can derive recurrence from the saved
section and energy evidence without rerunning separation or transcription.
It does not invent missing chroma, labels or motif matches. Evidence outside
the optional recurrence contract leaves motif evolution inactive; it must not
turn an otherwise usable saved analysis into a required neural rerun.

The permitted one-sample background playback-clock reconciliation also carries
forward chroma only from a previously validated evidence/sidecar pair, then
rebuilds and validates the new timeline binding.

Optional recurrence bounds are 360,000 energy frames, 72,000 chroma frames
and 512 sections. At the current 20 ms energy step the energy bound is two
hours; a supported longer show still completes its base music analysis. When
a bound is exceeded, the worker returns a requested-but-unavailable recurrence
marker with `reason: "evidence-size-limit"` and the exceeded limit names. It
neither truncates the evidence nor retries neural inference. Vocal expression
and the base composition remain available; motif evolution stays inactive.
