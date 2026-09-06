# LightForge 1.6.0

Install **LightForge-1.6.0.apk** over the existing app to keep your projects. The private update-signing identity is unchanged. Do not uninstall first.

## Quality comes first

The new analysis separates singing from the stereo music before analyzing vocal expression. It uses UVR MDX-Net Voc FT with polarity refinement and overlapping reconstruction, then the trained Frame-MN10 sound-event model on the isolated voice. It follows vocal entrances, syllabic attacks, pauses, estimated pitches and held notes. Bass analysis listens to the remaining accompaniment while the full Beat This! rhythm transformer remains the default.

The composer uses distinct articulation gestures, supported fades, sustained-note shapes and pitch-responsive cabin colour. Accompanying rhythm and bass retain their roles. Short words and notes cannot start long Dance sequences that outlast their musical passage; preparation, travel, recovery and command budgets still constrain all movement.

Analysis is deliberately more demanding. All models run offline and are bundled; no account, paid service, API key, setup or model download is required. Actual processing time and memory on your phone remain unmeasured.

## Hear and correct what the app understood

- Listen to Full song, Voice or Instruments on the same playback clock.
- Inspect detected phrases and measured notes, seek to their boundaries and repeat a passage.
- Mark a passage Voice or Instrumental, restore automatic interpretation, and Undo/Redo edits.
- Use Full song, Voice first and Bass first emphasis presets without losing the other musical layers.

Existing 1.4/1.5 arrangements reopen with their original checked frame payload. **Analyze voice detail** (or **Re-analyze music**) on an existing project once for the new voice separation and detail. Cached listening layers may need regeneration after storage cleanup or restoring a backup; saved shows still export using the original soundtrack.

## Verification and practical limits

In the 18 reference-mixture and controlled-remix cases, the final analysis retained voice in all 12 positive examples and produced no vocal events in the six instrumental controls. Those short tests do not establish universal accuracy.

The source archive includes real multitrack-reference comparisons, exact frontend and sample-clock checks, vocal/bass component tests, actual browser inference, project migration, listening/editing, command constraints and export checks. Detailed evidence and its scope are in `VALIDATION.md` and `qa/release-1.6.0/`.

Source separation, vocal pitch and phrase boundaries remain estimates. Dense or heavily processed vocals can retain instrument bleed or be missed. These are acoustic articulations, not lyric or word-by-word alignment. A 15/20 ms export step does not establish equal musical or physical accuracy.

No physical Android phone or Tesla was tested here. The preview follows exported commands; lamp optics, hardware latency and Tesla-controlled Dance strokes remain estimates.

The private source ZIP includes the signing material needed for compatible updates. Keep it private.
