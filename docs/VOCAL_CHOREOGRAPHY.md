# Acoustic vocal choreography bridge

`vocalChoreography: true` is an explicit engine setting. Since 2.3.0 the Studio
requests it for new projects through **Follow musical expression**. Restoring
a saved project keeps absent or explicitly false settings off. The engine
itself remains opt-in and does not change legacy frame bytes or FSEQ output when disabled,
when enrichment is absent, or when any validation proof fails.

The bridge is intentionally not a recognizer. It consumes only the acoustic
`LightForgeVocalSemantics` sidecar and its exact current semantic-timeline
receipt. It never accepts lyric, word, phoneme, or text fields and never
creates a vocal event or vehicle command.

## Activation contract

The bridge is active only when all of these are true:

1. `vocalChoreography` is exactly `true`.
2. The source result contains `vocalSemantics`, `vocalSemanticLinks`, and the
   current `semanticTimeline` on the original decoded-audio clock.
3. `LightForgeVocalSemantics.validate(sidecar, {duration, vocals})` succeeds
   against the current separated-vocal evidence.
4. `LightForgeSemanticTimeline.validate(semanticTimeline)` accepts the exact
   schema-v2, original-decoded-audio timeline. Malformed containers, invalid
   caps, unsupported schemas, and resampled clocks are rejected before a link
   is considered.
5. The bridge recomputes `linkTimeline(sidecar, semanticTimeline)` and requires
   canonical exact equality with the supplied receipt. A matching fingerprint
   alone is insufficient.
6. No vocal-region or manual vocal-cue edit has replaced the source evidence.

Invalid, stale, missing, edited, or linguistic sidecars fail closed and publish
an inactive diagnostic reason. They do not emit a fallback cue and do not alter
the base analysis cache.

## Bounded planning hints

The bridge annotates existing eligible vocal candidates only:

| Acoustic evidence | Controlled visual hint |
| --- | --- |
| Primary/secondary acoustic articulation stress | Bounded collision priority and strength boost for the existing attack; the added boost cannot cross the automatic structural/climax priority ceiling. |
| Held note | Legal release ramp on the existing sustained candidate. |
| Measured phrase release before its analysis span ends | Shortens only an existing phrase-scale candidate that already covers the release; onset is never moved. |
| Confident rising/falling pitch trajectory | Uses the existing left/right signature route as a spatial direction hint. |

The existing density budget, semantic hierarchy, collision resolver, vehicle
constraints, frame quantization, and FSEQ validator remain the final authority.
The bridge neither bypasses nor relaxes any of them.

`show.choreography.vocalChoreography` and
`show.choreography.lighting.vocalChoreography` expose request status, exact
sidecar/timeline bindings, link counts, and the number of hints actually
applied. They do not include lyrics or other linguistic content.

## Integration order

This bridge has two prerequisites and must be integrated in this order:

1. `73c9eac5c8776cba9927466668d5aea5792c4674` — clock-invariant acoustic
   vocal semantic enrichment (including measured `releaseTime`).
2. `fe1ade7daa719e753293fede17e5642fa6815cfd` — opt-in semantic choreography.
3. This bridge commit — both browser and composition-worker load order is
   `analysis/semantic-timeline.js` → `analysis/vocal-semantics.js` →
   `engine/semantic-choreography.js` → `engine/vocal-choreography.js` →
   `engine/show-engine.js`.

The analysis asset manifest and release verification pin must be regenerated
from the combined tree. Do not copy a staging manifest hash or accept a stale
verification receipt.

## Limits

This is acoustic alignment, not transcription. `syllableLike` means a supplied
acoustic attack only. It does not claim speaker identity, lead/backing role,
lyrics, words, phonemes, or semantic stress. Separation artifacts, vocal
doubles, highly processed voices, screams, rapid delivery, and sparse vocal
evidence remain confidence-limited and may leave the bridge inactive.


## Studio activation and saved evidence

New projects request acoustic enrichment, vocal choreography, semantic hierarchy
and recurrence/motif planning together. The switch can be turned off per project.
An existing version-8 analysis can gain freshly validated sidecars and an updated
composition directly from its saved musical evidence, without decoding audio,
rerunning Deux/GAME or changing an analysis refresh epoch. Undo restores both
its original analysis and exact frame sequence. Earlier or incomplete analyses
request ordinary resumable analysis when enriched evidence is unavailable.

Semantic density control preserves exact selected vocal/bass source attacks.
Nearby decorative cues can still yield around strong phrases; a lower salience
tier alone must not erase an already selected measured note or articulation.
Collision allocation, vehicle constraints and final frame validation still apply.
