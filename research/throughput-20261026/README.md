# Separation, vocal inference and PCM throughput observations

These are host observations for unreleased changes after `e434d38`. They cover
original-model separation screens and GAME execution, generated-audio conversion
and memory-backed WAV reads. Complete analysis and phone performance are unmeasured. Samples,
resampling, model inputs and analysis settings are retained.

## Separation remains the main compute cost

The retained [phone run](../inference-device-regression-20260928/README.md)
spent 86.39% of job time in source separation. Native passage profiles likewise
put most elapsed time inside the original neural graphs; session loading, FFTs
and copies are smaller costs. This is the priority for further runtime work.

The [engineering screens](deux-screening.json) preserve the subsequent decisions.
Fixed temporal batch sizing produced tiny Float32 differences with inconclusive
timing and higher memory; inter-operator parallelism and dynamic work scheduling
did not justify a change. Single-graph tests suggested a smaller worker pool,
but one complete original-model passage rejected that conclusion: baseline,
two-worker and existing four-worker times were 81.216, 85.278 and 47.991 seconds,
with process peak RSS of 855.5, 943.5 and 995.9 MB. All three complete finite
outputs had identical bytes and preserved every graph, frame and sample.

These are exploratory host observations with one ordered full-passage run per
schedule, no excluded warmup and variable host conditions. They do not establish
a new speedup or phone memory eligibility. The existing production schedule,
admission criteria and original model identities remain unchanged. The summaries
are engineering notes, not a complete reproducible qualification archive.

A grouped tensor-copy refactor was also reverted. Equivalent warmed calls to
both actual helpers showed median measured allocation of zero bytes for the
original helper on this host JVM and 161,280 bytes for the candidate, with
essentially equal time.
Source-level temporary-view counts therefore did not establish a useful heap
or speed improvement, and no Android allocation claim follows from this test.

## Native GAME pairing

The [equal-length comparison](game-pair-equal.json) uses the original adjacent
16-second contexts at sample spans `[441000,1146600)` and `[970200,1675800)` of
the complete public demo, with their original seeds. One excluded warmup pair
and three alternating measured pairs ran in fresh JVMs with the original pinned
graphs and ORT 1.25.1. All unrounded note bits matched in every comparison.
Both variants executed all 24 original graph calls; the paired path initialized
five sessions instead of ten and retired everything before returning.

Median time changed from 55.374 to 45.237 seconds, an **18.3% reduction**. Two
timing pairs improved; the third regressed from 39.824 to 49.885 seconds.
Median process peak RSS changed from 901596 to 919484 KiB, about 2% higher.
These are variable host observations on full-mixture audio, not isolated-vocal
accuracy, Android memory/thermal behavior, or a whole-song speedup. The engine
comparison does not measure the complete WebView/native transport memory peak.

The earlier [mixed-length comparison](game-pair-variable-rejected.json) preserved
notes but increased median time by 13.8%. Automatic scheduling therefore requires
equal sample counts; it does not pad or shorten the original contexts. The
five-graph topology and eight diffusion steps are unchanged.

With the original graphs prepared and the pinned host JARs in a dependency
directory, reproduce equal-length execution on Linux using an installed JDK:

```bash
python3 tools/benchmark_game_pair.py --dependencies /path/to/pinned/jars --first-passage 1 --output /tmp/game-pair-new
```

## PCM conversion and decoding

The [observations](observations.json) retain all measured trials and source
identities. Complete 30-second 44.1 kHz conversion medians changed from
404.60 to 159.96 ms; 48/96 kHz results were more variable. Final stereo PCM16 read
medians changed from 37.66 to 11.07 ms, and stereo-to-mono reads including the
original FIR changed from 143.42 to 121.74 ms. These stage percentages cannot be
added together or applied to total song-analysis time.

Rhythm routing eliminates repeated constant pitch calculations: 50,000 become
100 for the first 500-frame chunk and zero for unchanged subsequent chunks.
Its full-stage timing was inconsistent, so no percentage gain is claimed. The
bass coefficient experiment was discarded.

Reproduce with the focused tools from the repository root:

```bash
python3 tools/benchmark_wav_converter.py --seconds 30 --output /tmp/wav-conversion-new.json
node tools/benchmark_wav_decode.cjs --output /tmp/wav-decode-new.json
```

Run timing workloads separately. Earlier overlapping and pre-final decoder runs
remain explicitly labelled in the observation record. The Java harness also
executes the existing WAV importer checks; its throwing Android/FSEQ stubs do
not exercise those platform APIs. None of these records is release admission
or a new result for the registered native-inference campaign.
