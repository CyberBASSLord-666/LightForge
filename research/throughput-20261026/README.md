# Vocal inference, import and PCM throughput observations

These are host observations for unreleased changes after `e434d38`. They cover
original-model GAME execution, generated-audio conversion and memory-backed WAV
reads. Complete analysis and phone performance are unmeasured. Samples,
resampling, model inputs and analysis settings are retained.

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
