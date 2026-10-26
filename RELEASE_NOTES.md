# LightForge 2.4.3

LightForge 2.4.3 combines musical-display refinements, faster audio and vocal
processing, and a leaner offline APK.

## Improvements

- More deliberate instrumental hierarchy and decoration density. Protected
  vocal, pitched-bass, beat, bar, phrase and impact attacks retain priority.
- Shared nearest-frame timing for interior RGB and exterior lights, cleaner
  recovery across silent gaps, and full movement-cycle settling checks.
- Calibrated closure preview and validation use the compiled output commands.
- Bounded native GAME pairing reuses model setup for adjacent equal-length
  passages while retaining each original context, seed and language.
- Faster PCM import, mono/stereo WAV reads and repeated rhythm-band routing.
- Preview build sources and a research-only historical rhythm graph are omitted
  from APK payloads. Required offline models, notices and runtime assets remain.

## Updating

Install this original-signed update over the existing app. **Do not uninstall
first.** Keep exported project backups before moving devices or clearing app data.
The app continues to operate offline without accounts, API keys or runtime model
downloads.

## Performance scope

The retained host comparison of equal-length GAME passages measured 18.3% lower
median time with identical unrounded notes and about 2% higher peak process RAM.
Import and decoding observations apply to those individual stages. These figures
are not additive; complete-song acceleration and phone performance remain
unmeasured. Source separation remains the main compute cost, using the existing
qualified schedule and original model precision and context.

The release verification report records the exact APK, source and original
signing identity. Physical phone and Tesla observations remain optional and are
not claimed by the automated checks.
