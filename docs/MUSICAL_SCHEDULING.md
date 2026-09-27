# Musical scheduling and synchronization

LightForge 2.4 preserves the decoded soundtrack clock from measured musical
events to FSEQ commands. Composition remains deterministic and does not change
the analyzed audio or fabricate source-specific notes from generic transients.

## Source spans own their timing

Vocal phrases, separated vocal articulations, and bass notes are now scheduled
as continuous source spans. An arrangement-section boundary no longer drops a
short entrance segment, retriggers a held note, or starts its release early.
Global and per-part corrections retain their existing roles; the export frame
is selected only after the musical target time and offset are resolved.

Independent attacks preserve the same 80 ms separation on a physical output
across section boundaries as within them. An unresolved collision suppresses
a candidate instead of moving its attack later. Sustained source cues may span
sections, while silence gating, manual ownership, and disabled outputs still
apply to the final frame buffer.

If a negative global offset places an attack before the export begins, any
surviving held source starts at frame zero. Its source time and requested
offset interval are retained alongside the actual clipped frame interval.
SyncReview reports the attack as `outsideExport`, separately reports whether
the continuation is visible in the final bytes, and excludes that continuation
from attack-accuracy statistics. A positive offset may similarly truncate a
source at the final off frame. Neither boundary moves the planned release
earlier. When an opening source's release already began before export, the
remaining tail uses a legal hold/off instead of pretending that a ramp-down
command can initialize a partially lit lamp.

Musical cue holds share this soundtrack-offset behavior. Direct manual output
cues retain their absolute export times; negative manual source times remain
invalid. Manual output masks cannot count as observed automatic continuation.

## Deliberate spatial balance

When a gesture requests both members of a left/right fixture pair, the planner
reserves and allocates that pair together. A conflict cannot silently turn it
into a one-sided flash. Pairs on different physical fixtures remain independent,
so a rejected headlamp pair need not erase available tail lamps or center
outputs. Alternating accents remain intentional one-sided gestures. Disabling
one fixture does not disable its available counterpart.

The lighting diagnostics report requested, accepted, reserved, filtered, and
collision-suppressed pairs. These counts describe command allocation rather
than a perceptual symmetry score or proof of a particular car's hardware.

## Strongest measured detail wins

Off-grid transients are ranked by measured strength before local same-band
spacing is applied. A weaker early precursor no longer removes a stronger
nearby transient. Selected attacks retain their measured time; this does not
snap a singer, bass note, or transient to an invented beat grid.

Overlapping activity regions are merged without mutating source evidence.
Role lookup also retains a sustained note after a shorter overlapping note
ends, preventing artificial silence in the interior's musical response.

## Verification and limits

`tests/musical-scheduling.test.cjs` independently checks FSEQ attack bytes for
source entrances immediately before a section boundary at both 15 ms and
20 ms frame intervals and negative/positive offsets. It checks source release
timing, pair allocation under asymmetric collisions, disabled fixtures,
one-sided semantic filtering, strongest-transient selection, overlapping
source/activity intervals, and opening/ending clipping under signed offsets.

The command quantization bound is half an export frame for accepted musical
attacks. It does not measure audio-detection error, vehicle playback latency,
mechanical travel, or perceived musical quality on arbitrary recordings.
The existing physical-output constraints, final-frame synchronization review,
and full regression gate remain authoritative. Regeneration uses the updated
planner; already compiled saved sequences retain their stored frames.
