# Evidence-aware rhythm hierarchy

`web/analysis/rhythm-hierarchy.js` is an opt-in, additive interpretation layer
over LightForge's approved rhythm summary.  It is not a replacement beat
tracker, source of fabricated musical events, or a second model pass.

Enable it explicitly for an analysis request:

```js
options.rhythmHierarchy = true;
```

When enabled, the rhythm worker attaches `result.rhythmHierarchy` after the
existing `LightForgeDSP.summarize(...)` output has been produced.  The legacy
`beats`, `downbeats`, `beatDetails`, `bpm`, `meter`, phrases, sections, and
their timings are left untouched.  When disabled (the default), no hierarchy
field is attached and the rhythm result remains on the legacy path.

## What it represents

The sidecar contains confidence-carrying views of the existing evidence:

- micro-onsets and only evidence-supported subdivisions;
- approved beats and downbeats, with local BPM and bar-position context;
- observed bars derived only from approved downbeats;
- bounded tempo segments and tempo-change uncertainty;
- legacy meter evidence plus confidence-ranked alternatives from approved
  downbeat spacing and existing bar-position evidence;
- existing phrase and section spans.

It handles local half/double-time and meter disagreement conservatively.  A gap or an
unexpectedly short interval becomes an ambiguity record with candidate tempo
interpretations; it never changes, inserts, deletes, or re-times the approved
beat grid.  Likewise, unsupported meters, missing downbeats, and weak bar
evidence remain uncertain rather than being guessed.  An alternative meter is
only an uncertainty record: the legacy meter and approved beat grid remain
authoritative.

## Cache and validation contract

The hierarchy has `schemaVersion: 1` and a deterministic `inputSignature`
formed from the validated legacy rhythm evidence plus the consumed onset,
phrase, and section maps.  `validate(hierarchy, analysis)` rejects a sidecar
whose beat map, downbeats, meter, confidence, duration, or consumed structural
evidence changed.  `attach(analysis)` then rebuilds it from the already cached
approved summary; it does not rerun model inference and does not accept
non-finite, unsorted, off-grid, or mismatched beat-detail data.

The worker uses this contract for cached rhythm results too.  On an opt-in
restore it reuses a valid hierarchy; a stale or absent one is rebuilt from the
validated cached rhythm result and the rhythm checkpoint is atomically updated.
If validation fails, the sidecar is omitted rather than interpreting untrusted
model output.  A hierarchy-only schema upgrade therefore does not force source
separation or other downstream analysis to rerun.

## Limits

This layer does not claim new beat/downbeat/meter accuracy.  Its confidence
values describe the evidence supplied by the existing rhythm summary and its
internal consistency.  Its tempo segments are conservative support summaries,
not a ground-truth tempo annotation.  Promotion of this opt-in sidecar to a
default choreography input requires locked-corpus quality-gate evidence.
