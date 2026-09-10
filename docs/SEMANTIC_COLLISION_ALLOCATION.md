# Semantic collision allocation (experimental)

This opt-in planner mode gives a caller a controlled way to preserve a **known, high-salience semantic target** when every configured preferred light route is already unavailable at the target's original musical-clock span.

It is deliberately narrow:

- Disabled or absent settings preserve the legacy planner result. The allocation pass does not run and adds no diagnostics.
- The caller supplies the semantic event identifier, original-clock span, salience tier/score, preferred outputs, and fallback output groups. LightForge does not invent targets, lyrics, semantic labels, or fallback routes.
- A fallback is only added after every preferred route fails the normal physical-lane placement test. If any preferred route remains available, the target is skipped to avoid duplicating an accent.
- Fallback groups are atomic. Every group member must be a configured, available light output and must fit its lane. The planner never emits only part of a requested symmetric group.
- The allocation never moves, shortens, replaces, or time-shifts an accepted cue. It only adds a real light cue at the requested span when an otherwise idle configured fallback group can realize it.
- The mode requires a high tier and a score at or above `minimumSalience`; its defaults are `structural` / `climax` and `0.78`.

## Contract

Pass this through `ShowEngine.generate(..., settings)`:

```js
{
  collisionAllocation: {
    version: 1,
    enabled: true,
    minimumSalience: 0.78,
    maxAllocations: 64,
    tiers: ['structural', 'climax'],
    fallbacks: {
      climax: [['left-repeater', 'right-repeater']],
      structural: [['left-rear-turn', 'right-rear-turn']]
    },
    targets: [{
      semanticEventId: 'm000042',
      time: 42.5,              // original music clock, seconds
      end: 42.72,
      tier: 'climax',
      salience: 0.95,
      role: 'structure',       // optional safe identifier, never lyric text
      candidateOutputIds: ['left-outer'],
      // Optional per-target route list; takes precedence over fallbacks[tier].
      fallbackOutputGroups: [['left-repeater', 'right-repeater']]
    }]
  }
}
```

The normalizer rejects unknown fields, invalid IDs/spans/scores, unavailable or non-light outputs, duplicate or overlapping output channels within a group, preferred/fallback overlap, and a target without a configured fallback.

A target can name `preferredOutputIds` instead of `candidateOutputIds`, but not both. It must use one. The semantic event identifier is a safe opaque identifier, not displayed lyric content.

## Diagnostics and realization evidence

When enabled, `lighting.diagnostics.semanticTargetAllocation` is bounded to at most 128 attempted target rows and includes:

- requested, eligible, allocated, suppressed, skipped, and omitted target counts;
- the canonical input identifier/span/tier/score;
- preferred output IDs and any chosen output group;
- an `allocated`, `suppressed`, or `skipped` outcome plus a machine-readable reason.

Allocated cues are present in `lighting.events` with:

- `semanticFallbackAllocation: true`
- `semanticTargetId` and `semanticEventId`
- `semanticTier`, `semanticSalience`, and optional `semanticRole`

They are normal accepted light cues, so the FSEQ frame data contains the fallback activation. They intentionally do not receive a regular musical `role`; an allocation must not inflate vocal or bass coverage metrics.

## Quality caveat

This is not automatic collision diagnosis and does not prove that the supplied semantic target was correctly detected or that a fallback is perceptually superior. An upstream quality gate or reviewed semantic timeline must choose targets that were otherwise fully lost. The mode refuses to add an accent when a preferred route remains usable, but it cannot independently establish musical correctness, vehicle photometric response, or human perceptual preference. Keep it experimental until a representative quality corpus validates the chosen target/fallback policy.
