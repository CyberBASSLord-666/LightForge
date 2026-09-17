# Tonal structure and measured phrasing

New analyses use the existing production spectral frontend to recognize sustained
changes in pitch-class content as well as loudness and spectral colour. Equal-
energy harmonic transitions can therefore become section boundaries and change
scene selection in the default light and movement planners. Measured tonal
changes also take priority over the old fixed four-bar phrase division. A
three- or five-bar passage can retain its measured ending.

The implementation is in `web/analysis/dsp.js`, inside the existing
`performance.structural_analysis` timing scope. It adds no neural inference,
resampling or alternate beat decoder. The original decoded-audio clock,
approved beats, downbeats, model precision and separation/transcription inputs
remain authoritative. Existing saved projects retain their stored analysis;
reanalyzing creates the new structure.

## Evidence and limits

The detector computes local novelty from the existing 12 pitch-class features.
It removes their common floor only after a concentration and audio-level gate,
then normalizes each frame. Flat broadband features, very quiet frames and
malformed or incomplete chroma cannot establish a tonal boundary.

The core contrast is half the squared distance between neighbouring mean
feature vectors. For dot-product similarity this is the normalized box
checkerboard contrast, computed with prefix sums without allocating a full
self-similarity matrix. This follows the novelty-segmentation principle
described in the [FMP novelty segmentation reference](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C4/C4S4_NoveltySegmentation.html).
LightForge combines adjacent time scales and local peak prominence; the
thresholds are implementation choices, not trained or calibrated probabilities.

A confident meter sets one-, two- and four-bar analysis windows. Otherwise the
windows use bounded seconds, without guessing new beats. Both scales must agree
before a phrase or section candidate is offered. Complete context is required
on both sides of a peak, avoiding false transitions where a large window first
becomes available. Explicit silence boundaries are protected before other
candidates are selected.

Section and phrase records expose `estimated: true` and `boundarySource`.
`tonal-novelty` identifies measured harmonic change;
`energy-spectral-novelty` identifies existing dynamics/colour evidence;
`meter-scaffold` identifies a four-bar fallback, with lower confidence. Scaffolds
fill unsupported spans and never subdivide explicit silence. These are musical
planning estimates, not chord names, keys, verse/chorus labels, lyric alignment,
or ground-truth phrase annotations. A passing chord is not automatically a new
section, and an off-grid boundary is not moved when no trustworthy grid is
available.

`music.structure.version` is 2 and includes a compact tonal-evidence summary.
The release asset manifest binds the changed DSP source into the analysis
implementation fingerprint, so an old completed analysis cannot silently pass
as a new implementation's cache entry. The canonical analysis envelope remains
schema 8; its shape has not changed.

## Validation and resource cost

`tests/musical-structure.test.cjs` covers equal-energy harmonic changes,
three-bar phrasing, transposition, broadband floors, sustained and periodic
chords, a short artifact, missing/corrupt features, silence, uncertain meter,
and actual default-composer changes with an unchanged beat clock. A fixture
uses the production FFT frontend on major/minor chord PCM, showing boundaries
that the energy/spectral-only detector misses. These controlled fixtures verify
specific behaviour; they do not establish general music-detection accuracy or
listener preference.

The tonal pass scales linearly in feature frames and pitch classes, with bounded
local peak searches. At the four-hour product limit it adds roughly 8.1 MB of
working typed-array storage; it does not allocate a quadratic similarity matrix.
Existing feature arrays are reused. It adds no model work and must not be
reported as an inference-speed improvement.

For an explicitly supplied project/audio pair, run:

```sh
node tools/evaluate_musical_structure.cjs \
  --wav /absolute/path/lightshow.wav \
  --project /absolute/path/LightForge_Project.json \
  --baseline-dsp /absolute/path/baseline-dsp.js \
  --output /absolute/path/structure-comparison.json
```

This audit reuses the approved saved beat map, runs the production PCM reader,
resampler and feature extractor, and compares structural analysis and default
composition. The optional baseline is a captured previous DSP source; only its
private structure functions are exposed for the comparison. The report binds
source hashes and separates feature extraction from structure time. It is not
a cold full-pipeline benchmark, a new beat prediction, or an automatic accuracy
score against the supplied audio.
