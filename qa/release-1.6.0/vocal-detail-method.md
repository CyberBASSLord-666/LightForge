# Separated-vocal musical detail, LightForge 1.6

The detail extractor consumes actual trained-separator vocal PCM and optional accompaniment PCM. It never labels a selected frequency band as a separated voice. Singing and speech event scores are supporting semantic evidence; their scores are not calibrated probabilities.

`LightForgeVocalDetail.Extractor({sampleRate, duration})` supports 22,050 and 44,100 Hz mono Float32 input. Calls to `push(vocals, startSample, accompaniment?)` must cover the original clock contiguously. `finish({classifier, model})` accepts transient `singingScores`, `speechScores`, and `frameStep` arrays. It retains numerical features, not track-wide PCM. A incomplete, overlapping, non-finite, or differently sized stream rejects rather than inventing missing music.

## Musical information

- Source energy uses centered 10 ms windows on a 5 ms grid. All timestamps remain on the vocal sample clock; no drum onset, global offset, or beat quantization moves vocal events.
- A four-second local percentile with a confidence-gated 400 ms quiet-recovery context follows changing production levels. Strong semantic voice evidence or adequate stem isolation enables quiet recovery. A local vocal-to-accompaniment power check stops this recovery from amplifying weak separator leakage into confident vocal activity.
- The trained separator contributes independent source evidence when a sound-event classifier misses an unusual or distorted voice. A source-led candidate needs at least 2.5% of local combined vocal/accompaniment power, 20% of normalized local vocal level, a weak semantic voice seed of 0.035 within a one-second radius, and at least 200 ms of support. It must also occupy at least 35% of the candidate phrase and meet the same energy/silence checks. These thresholds select **uncertain vocal sources**, not confident singing. A periodic instrument with no voice seed or quiet instrumental bleed does not qualify just because it appears in the separated output.
- Phrase entrances and releases come from the isolated energy trace around learned vocal support. Short consonant gaps can remain inside a phrase.
- Articulation accents follow positive isolated energy change with a 100 ms refractory period. They are **estimated acoustic articulations**, not word boundaries or transcribed syllables.
- Periodicity is measured after centered anti-alias filtering to 11,025 Hz. An FFT autocorrelation with local energy normalization covers approximately 55–1,100 Hz in a 93 ms window on a 20 ms grid. Strong periodic maxima and local continuity support pitch estimates; stable segments must last at least 140 ms. Segments lasting at least 350 ms are labeled held notes. Ordinary vibrato remains inside a sustained note when evidence supports it.
- Speech-dominant phrases retain voice timing but do not generate sung-note contours. Ambiguous singing remains explicitly marked; it can still produce conservative source-timed voice accents.

The periodicity approach belongs to the classical autocorrelation family. The source-paper discussion of pitch estimation for speech and music is [de Cheveigné and Kawahara, 2002](https://pubmed.ncbi.nlm.nih.gov/12002874/). This is an original autocorrelation implementation, **not a claim to reproduce YIN exactly** and not a neural transcription model.

## Validation scope

`tests/vocal-detail.test.cjs` covers exact synthetic source times, pitch, vibrato, 40 dB dynamics including an adjacent quiet phrase, independently shifted accompaniment kicks, speech, instrumental leakage, noise, silence, arbitrary streaming seams, both supported rates, invalid stream rejection, short-file boundaries, minimum-note floating-point behavior, and four-hour bounded summaries.

`test-vocal-detail-reference.cjs` exercises six official licensed MUSDB original vocal stems using frozen learned event scores. These are identity and acoustic references, not hand-aligned lyric or note labels. Tests that use original stems evaluate the detail extractor, not separator inference quality. The independent music quality evaluation separately measures the full trained separation pipeline and controlled vocal removal.

`verify-vocal-detail.cjs` is the reproducible receipt producer. In addition to 16 independent DSP groups, it checks 18 cases using previously captured actual MDX output, the production float downsampler, and trained isolated-source classification: six original mixtures, six controlled vocal removals, and six accompaniment-only negatives. The source-led fallback recovers two uncertain NightOwl passages that the classifier threshold otherwise discards; all six actual-separator instrumental negatives remain without invented phrases, accents, or notes. This small regression set is not a general music benchmark. The whole public-worker evaluation separately binds complete inference execution.

No 5 ms grid, synthetic timing result, or acoustic reference proves 5 ms real-world accuracy. Reverb, bleed, multiple singers, distortion, unvoiced sounds, rapid pitch changes, and model mistakes can still produce missed or ambiguous events. Pitch follows a dominant periodic voice rather than every simultaneous harmony. Physical vehicle execution has not been evaluated by this module's tests.
