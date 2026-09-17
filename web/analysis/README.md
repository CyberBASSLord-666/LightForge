# LightForge offline music intelligence

`MusicAnalyzer.analyze(audioUrl, options, onProgress, signal)` returns analysis version 8.
Every runtime graph is bundled in the APK. Audio never leaves the device, and
there are no runtime downloads, keys, subscriptions or remote services.

| Stage | Studio (`precision`, default) | Balanced |
| --- | --- | --- |
| Rhythm and bar accents | Beat This! full | Beat This! compact |
| Stereo source separation | Mel-Band RoFormer Deux | UVR MDX-Net Voc FT |
| Singing/speech evidence | PretrainedSED Frame-MN10 | Same |
| Sung-note transcription | GAME Large 1.0.3 | Same |
| Bass notes | Harmonic tracking in vocal-separated accompaniment mixture (not a bass stem) | Same |

## Separation and original audio clock

Deux runs the author's full 13-second context, original checkpoint values as
Float32, 2,048-point centered STFT, 441-sample hop and both trained source heads.
The model is split into sequential ONNX sessions to bound working memory.
Attention query tiles retain the complete key/value context; there is no reduced
context, discarded layer or weight quantization. Ten-second owned regions retain
1.5 seconds of context on each side and overlap by five seconds with complementary
crossfades. Output sample counts equal the original 44.1 kHz source exactly.

Balanced mode retains the verified MDX pipeline: original stereo spectra,
7,680-point FFT, 1,024-sample hop, two polarity predictions, compensation 1.021,
normalized inverse STFT and complementary crossfades. Its accompaniment is the
original mix minus estimated voice. Neither mode applies reference-derived
latency correction, gain fitting, time stretching or beat snapping.

Both modes stream mono Float32 voice and accompaniment into private OPFS WAVs
at 22.05 kHz through the existing centered anti-aliasing filter. A separate
44.1 kHz Float32 voice WAV preserves the original source clock for GAME. This
cache needs approximately 21.2 MB per minute, is replaceable, and is omitted from
backups. Original stereo PCM16 audio remains the exported soundtrack. Aborted
jobs remove incomplete caches; missing caches do not invalidate saved shows.

## Neural singing and measured expression

Frame-MN10 supplies singing/speech evidence. The detail extractor measures
energy, source contrast and articulation on the actual estimated vocal waveform.
GAME Large predicts sung-note boundaries and pitch from that full-resolution
voice, with the author's eight diffusion steps and 0.2 thresholds. A supplied
seeded uniform-noise input replaces the graph's internal random operation;
original weights are unchanged. Twelve-second owned regions retain two seconds
of neighboring context. Carry-in notes are joined without inventing seam attacks.

GAME notes must overlap a supported non-speech phrase. A prominent separated source with weak general event-classifier scores can retain uncertain phrasing when GAME notes agree with independently measured periodic pitch; existing source-energy, duration and speech guards still apply. Classifier scores are never inflated. Speech and unsupported
regions cannot acquire sung-note gestures. Neural pitch and boundaries replace
acoustic note estimates; measured expressive energy and independent unvoiced
articulations remain. Confidence describes relative singing evidence, not a
calibrated GAME probability. Lead and backing singers remain combined. This is
singing-note transcription, not lyrics, exact word alignment or singer separation.

Bass tracking uses low-register harmonics in a vocal-separated accompaniment mixture.
The input has been separated from lead vocals, but it is not an isolated bass stem:
drums and other instruments remain, and real-song onset estimates can be ambiguous.
The semantic timeline records this as separated accompaniment context, never as
an isolated bass source.

Repeated notes at the same estimated pitch use a short-window harmonic
articulation pass after coarse pitch tracking. A low-band energy dip only
nominates a boundary; the note's own supported harmonics must fall deeply and
restart rapidly. This preserves measured attacks that the longer pitch window
can blur while rejecting smooth tremolo as a restart. The result remains an
accompaniment-mixture estimate, and overlapping kicks can still affect coarse
pitch spans or boundaries.

## Structure and musical-expression defaults

New analyses include multi-scale tonal structure and measured phrase boundaries.
Existing pitch-class features can identify a sustained harmonic change even
when loudness is unchanged; measured boundaries take priority over fixed
four-bar phrasing. Silence remains protected, and the beat/model clock is
unchanged. The default light and movement composers consume the improved
sections and phrases. See `docs/MUSICAL_STRUCTURE.md` for uncertainty,
controlled validation and the original-audio comparison tool.

New projects explicitly enable vocal semantic enrichment, recurrence analysis,
semantic choreography, vocal choreography and motif evolution. These settings
remain opt-in at the worker/engine API boundary (`=== true`); a restored project
with missing or false flags keeps those features off. Turning expression on
for a saved schema-8 analysis derives validated sidecars from existing evidence
without repeating neural inference. Fresh foreground and background analyses
receive the same explicit flags. See `docs/MUSICAL_EXPRESSION.md`.

## Acoustic vocal semantic sidecar

`vocalSemanticEnrichment: true` enables a validated sidecar after the
existing separated-vocal detail and GAME passes. It does **not** run another
model or inspect audio again. The sidecar normalizes already accepted vocal
regions/phrases, phrase onsets/releases, existing acoustic articulation markers,
existing notes, pitch trajectory, intensity, and stress confidence.

An articulation marked `syllableLike` is only a timed acoustic attack from
`vocalDetail.accents`; it is not a recognised syllable, phoneme, word, or
lyric. The sidecar deliberately contains no linguistic content. It has a
deterministic 64-bit source binding for its vocal evidence and is discarded/rebuilt when
that evidence or its schema changes. It is stored under the independent
`vocal-semantics` checkpoint, so changing this opt-in feature does not
invalidate separation, transcription, rhythm, or bass work.

The cached base semantic timeline and salience map remain unchanged by this
sidecar. Callers with enrichment disabled retain the existing path. When enabled, `vocalSemanticLinks` maps the
sidecar only to exact existing vocal events in the semantic timeline; a stale
or mismatched sidecar fails closed and is never converted into vehicle commands.
See `docs/VOCAL_SEMANTIC_ENRICHMENT.md` for the contract.

## Acoustic vocal choreography

`vocalChoreography: true` is a separate composition setting. It uses no PCM,
model, lyric, word, phoneme, or text input. When both the acoustic vocal
sidecar and its exact current semantic-timeline link validate, it can only
adjust existing vocal candidates: bounded articulation priority/strength,
legal held-note release, measured phrase release, and left/right direction
from an accepted pitch trajectory. It never creates a musical event or a
vehicle command. The canonical schema-v2 original-clock timeline validator
must pass before the link is used; malformed, stale, resampled, or edited
evidence leaves the bridge inactive. With the setting off, or when any proof fails, legacy frames and FSEQ bytes
are unchanged. New projects explicitly enable it; older project settings are
preserved.

See `docs/VOCAL_CHOREOGRAPHY.md` for the activation and output contract.

## Recurrence sidecar

`recurrenceAnalysis: true` adds a final, cache-isolated recurrence stage only
after the base rhythm, separation, voice, and bass stages complete. It reuses
the canonical semantic timeline plus existing validated energy/chroma features;
it does not decode audio again, invoke another model, alter the beat grid, or
invent musical labels. The stage emits a deterministic
`recurrenceAnalysis.enabled` provenance marker together with exact
`recurrenceEvidence` and `recurrenceSidecar` bindings. The base checkpoint
strips those opt-in fields, so API callers that omit or disable the flags
retain the existing analysis and FSEQ path.

A sidecar is still analysis data, not choreography. Motif evolution additionally
requires a current valid marker, valid evidence/sidecar binding, and both
`semanticChoreography: true` and `motifEvolution: true`. If any proof is
missing, stale, malformed, or inactive, planning fails closed to the
non-motif path. See `docs/RECURRENCE_MOTIF_SIDECAR.md`.

## Optional dedicated-percussion semantic input

The shipped worker does not currently include a dedicated drum/percussion model.
With its default settings it never promotes mix onsets, impacts, beat estimates,
accompaniment energy, or a low-frequency band into instrument-labelled drum
events. This remains an additive integration contract for a future dedicated
analyzer or a legitimate manual/annotation importer; it is not a claim that
those detections already exist.

For controlled experiments only, a caller may set
`enableEstimatedPercussionEvidence: true` on a fresh rhythm analysis. That
opt-in adds low-trust `mix-feature-estimate` evidence only when a localized
20 ms low/mid/high spectral-flux peak agrees with an independent 5 ms PCM
attack. It can emit only `kick`, `snare`, or `hat`; every event is marked
`estimated: true`, states that its input is the unseparated original mixture,
and has a confidence/salience cap. The cap keeps it below primary salience and
excludes it from automatic song-priority profiling. It does not claim a drum
stem or a drum model, is disabled by default, and therefore cannot change
default choreography or FSEQ output. Include this explicit setting in any
analysis cache identity so a cached default rhythm result is not reused for an
opt-in experiment.

A caller that has actual classed evidence may supply it with the analysis result:

```js
percussionAnalysis: {
  source: 'detector-or-annotation-id', // optional provenance
  model: 'optional-model-version',
  inputStem: 'drums',
  inputStemSeparated: true,
  sourceSeparated: true, // only when explicitly evidenced
  events: [
    {time: 12.48, kind: 'kick', confidence: 0.94, strength: 0.91},
    {time: 12.98, duration: 0.18, kind: 'fill', confidence: 0.78, strength: 0.72}
  ]
}
```

Only valid supplied entries with exact lowercase `kind` values
`kick`, `snare`, `clap`, `hat`, `crash`, `tom`, or `fill` are
represented as `percussion_*` timeline events on the `drums` semantic
source. Unknown labels, invalid time spans and missing input are ignored rather
than guessed. An input stem is not treated as separated unless
`sourceSeparated: true` is explicitly supplied.

A `kick_bass_coincidence` relationship/event is produced only when a valid
supplied kick falls within a valid `bassNotes` span (with a bounded 60 ms
onset/end tolerance). It records the source event IDs and timing delta. Generic
onsets, impacts, bass phrases and energy bands cannot create this relationship.
An opt-in `mix-feature-estimate` kick carries the same low-trust salience cap
through any derived coincidence; only separately supplied evidence can receive
normal percussion authority. The result remains deterministic for identical
inputs.

## Typed stem-routing contract

The current bundled pipeline has two actual separated cache layers: a combined
vocal layer and an accompaniment layer. The vocal layer is not labelled as a
lead-only stem, and the accompaniment layer is not promoted to drums, bass, or
harmonic isolation. The worker records the contract as additive
`stemRouting` metadata after final bass analysis or a matching cache restore.
It validates an existing contract and rebuilds only a missing or invalid one;
no model stage, source audio, choreography input, or analysis-version contract
is changed.

A future importer or analyzer can provide optional semantic stems on the same
original decoded-audio clock:

```js
LightForgeStemRouting.build({
  legacyStems: {
    vocals: {audioRef: 'stem-cache:.../vocals.wav'},
    accompaniment: {audioRef: 'stem-cache:.../accompaniment.wav'}
  },
  semanticStems: [{
    id: 'drum-pass-1',
    role: 'drums',
    audioRef: 'external://opaque-drum-reference',
    clock: 'original-decoded-audio',
    confidence: 0.91,
    provenance: {
      source: 'supplied-drum-analyzer',
      model: 'optional-model-version',
      isolationEvidence: 'declared'
    }
  }]
});
```

The permitted external roles are `lead-vocals`, `backing-vocals`, `drums`,
`bass`, and `harmonic`. Each requires an opaque audio reference, an
original-clock declaration, a confidence in [0, 1] when supplied, and
provenance. `isolationEvidence` is one of `verified`, `declared`, or
`unknown`; the router preserves that statement rather than upgrading it to a
physical separation claim. Legacy cache records carry the distinct
`pipeline-separated` evidence label.

`LightForgeStemRouting.route(contract, task)` selects only eligible existing
records. It prefers a lead-vocal stem for vocal transcription, an external
drum/bass/harmonic stem for the matching task, and may use legacy accompaniment
only as an explicitly named mixture fallback for bass or harmonic analysis.
There is deliberately no drum fallback from onset, impact, accompaniment, or
energy data. Missing, duplicate, unsupported, unclocked, or unprovenanced
descriptors are reported as rejected and do not create a route.

## Rhythm, memory and cancellation

Beat This! retains the full/compact author models, exact log-mel frontend,
overlapping 30-second contexts and original-clock feature extraction. Frame
edges follow the upstream context policy. Earlier BeatNet assets remain only
for historical reproducibility. ONNX Runtime Web 1.20.1 is unchanged.

Sessions are released between stages. WASM may retain its peak allocation until
the disposable worker terminates. Studio processing can take much longer than
the soundtrack and needs several GB of working memory. Balanced is explicitly
selected by the user; failures do not silently switch models or fabricate results.
Keep the app open while analyzing. Abort terminates the worker and retries cache
cleanup while WebView releases its writable handles.

## Reproduction, licenses and evidence

`tools/prepare_deux.py` and `tools/prepare_game.py` verify pinned official source
archives/checkpoints and reproduce the graphs. `ASSET_MANIFEST.json` binds every
runtime file, graph, model manifest and notice. Builds reject missing, unexpected
or modified analysis assets. See `BUILD.md` at the repository root.

- Deux: [becruily](https://huggingface.co/becruily/mel-band-roformer-deux), weights
  CC BY-NC 4.0; architecture code from ZFTurbo/lucidrains and contributors, MIT.
- GAME: [openvpi](https://github.com/openvpi/GAME), original and modified models
  CC BY-NC-SA 4.0. Attribution and modification notice accompany the graphs.
- Beat This!: [CPJKU](https://github.com/CPJKU/beat_this), MIT; ONNX distribution
  [danigb/beat-this-rs](https://github.com/danigb/beat-this-rs), MIT.
- Frame-MN10: [PretrainedSED](https://github.com/fschmid56/PretrainedSED), MIT.
- MDX: [Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui),
  notices, model parameters and checkpoint provenance remain bundled.
- ONNX Runtime: Microsoft and contributors, MIT.

Current runtime, parity and small reference-set results are in
`qa/release-2.1.0/`. Original vocal stems are scoring references, not production
separator inputs. Component tests using an original stem are labeled separately.
The six short MUSDB excerpts are not representative or verified held-out data;
training overlap is possible. Desktop WASM, parity and source-clock sample counts
do not establish human note accuracy or physical Android/Tesla performance.
