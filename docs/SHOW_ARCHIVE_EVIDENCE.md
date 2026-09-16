# Evaluate an exported show locally

A normal LightForge export can provide reproducible compiler evidence without
asking its owner to time another phone run. The ZIP contains the full playback
WAV, final FSEQ, and a project snapshot with saved analysis, settings, model
provenance, and compressed compiled frames.

Run from a complete repository checkout with Python 3.11+ and Node 22+:

```bash
python3 tools/evaluate_show_archive.py \
  --archive /absolute/private/Show.zip \
  --output /absolute/private/show-evidence.json \
  --require-exact
```

The destination must be a new file outside the repository. The tool makes no
network requests and does not install dependencies. It processes the original
archive read-only, stages required members in a private temporary directory,
removes those copies on completion, and saves a JSON report with mode `0600`.
User songs, project snapshots, and derived reports must stay out of public Git
history. The report contains timestamps, output diagnostics, member names, and
content hashes, but no audio payload or full project snapshot.

The expected members are:

| Member | Use |
| --- | --- |
| `LightShow/lightshow.wav` | PCM format, sample count, duration and checksum |
| `LightShow/lightshow.fseq` | Actual exported header and command frames |
| `Review/LightForge_Project.json` | Saved detector output, settings and compiled snapshot |
| `Review/Validation.json` | Optional historical FSEQ checksum comparison |

Every ZIP file member is streamed through CRC verification and SHA-256 hashing.
The wrapper rejects traversal paths, links and special files, duplicate or
case-ambiguous names, incompatible compression, encrypted members, and expanded
size violations. It never calls `extractall`. Defaults allow at most 128 entries,
3 GiB total expanded data, 64 MiB per JSON member, and the existing compiler's
960,000-frame limit. `--max-total-bytes` can change the total archive budget.
Only the application's stereo 44.1 kHz, 16-bit PCM WAV and uncompressed 200-channel
FSEQ 2.0 with 15 or 20 ms steps are supported. Other formats produce an explicit
error instead of an incomplete success.

## What the tool checks

`evaluate_show_project.cjs` uses the existing worker harness to run the actual
production worker's restore operation. This checks the saved music/settings
input digest, metadata digest, bounded gzip expansion, frame digest, current
channel and movement rules, and preview preparation. It does not duplicate those
rules. The companion has a small FSEQ envelope reader because the repository
has no shared FSEQ parser; the production engine validates the exported payload.

The current `ShowEngine.generate()` then runs against exactly the saved analysis
and settings. The report separates these questions:

- **Archive integrity:** Do audio duration, FSEQ dimensions, current export
  validation, saved frame bytes, and any supplied native checksum agree?
- **Frame equivalence:** Does the current compiler reproduce every saved frame
  byte? A mismatch records changed-byte count and the first frame/channel.
- **Complete FSEQ equivalence:** Does current header plus payload equal the
  original FSEQ? A producer-version header change can differ while frames remain
  identical.
- **Command realization:** What vocal/bass targets did the current compiler
  select, match or suppress, with what timing distributions and collision losses?
  Historical synchronization diagnostics and freshly recomputed diagnostics are
  labeled separately.

The report binds the run to a SHA-256 inventory of the relevant local source
files, including uncommitted changes, and checks that inventory again after
replay. The Git commit alone is not treated as a complete source identity.
Single-run host compiler and saved-restore durations are recorded separately
from historical audio-analysis timings.

Exit status is `0` for an evaluated archive whose integrity checks pass, `1` for
invalid input or execution failure, and `2` for failed integrity checks. With
`--require-exact`, frame or complete-FSEQ differences also return `2`. A completed
evaluation still writes its report when returning `2`, so differences can be
reviewed. Existing reports are never overwritten. Omitting `--require-exact`
allows candidate compiler changes to be evaluated and inspected without treating
all intentional output changes as tool failures.

## Timing and quality boundaries

The recorded pipeline attempt may restore rhythm or separated stems while
rerunning vocals and bass. A restored stage can report `seconds: 0` while its
actual profile records nonzero restoration wall time. The tool reuses
`project_performance_timings.py` to interpret executed stage timing probes and
keeps those observations separate from declared times.

Separation model metadata can retain the duration of an earlier, expensive
attempt. It is reported as historical metadata and is never added to the current
attempt. Inclusive stage wall times overlap internal model-inference spans.
They must not be summed into a new total.

`coldStartVerified` is always false for this exported evidence, and
`speedupPercent` is always null. Stage cache misses alone do not prove that
internal checkpoints, operating-system caches, or model initialization started
cold. A controlled baseline/candidate analysis pair on the same hardware and
settings is needed for a defensible speedup measurement.

Synchronization coverage here is against targets from saved automatic music
detection. It does not establish that the detector found every real beat, word,
vocal note or bass attack correctly. Mechanical command lead times and preview
motion estimates are not measurements of physical Tesla response. This tool
performs no fresh model inference, independent audio labeling, Android lifecycle
run, physical vehicle test or release qualification.

The included full PCM can separately support fresh model runs. Saved stem-cache
references do not imply that separated stems are present in the ZIP; inspect the
reported inventory before attempting to reuse those files. The deterministic
project snapshot remains useful for compiler, restoration and export regression
checks even when model evaluation must rerun separation.

## Focused tests

```bash
python3 -m unittest tests.test_evaluate_show_archive -v
```

The tests generate a genuine worker snapshot from synthetic inputs. They cover
exact replay and target timing, restored-stage accounting, tampered settings,
modified exported commands, header-only differences, incomplete audio,
duplicate JSON, traversal/link/duplicate ZIP entries, expansion limits, CRC
corruption, malformed FSEQ, and output privacy/overwrite restrictions. The
existing production Python test discovery includes this `test_*.py` module.
