# LightForge 2.4.2 verification source protocol

This directory contains the source helpers for a fresh 2.4.2 verification run.
It intentionally contains no receipts, logs, screenshots, retained model outputs,
or prior release results.

This is draft next-build source preparation, not evidence of a completed run,
release approval, or permission to build or publish. It carries forward the
2.4.1 verification requirements for the proposed 2.4.2 / 20402 identity. Its
producer identities and source inventory refer to this release. The sealed
evidence manifest and Android background validator continue to require the
native GAME outputs and emulator exercise; advancing the version does not
remove either check. The publisher still requires the exact qualified source,
source-bound automated evidence and original signing identity.

No historical approval or successful receipt is promoted by this migration.
The release-quality declaration and inference-improvement gate separately
determine qualification. A passing protocol alone does not establish the 75%
speedup objective, general music quality, exact installed vehicle equipment, or
physical phone/Tesla behavior. Those claims require their corresponding
measurements; no physical phone/Tesla observation is introduced here.

## Fresh session-bound producers

The production verifier creates one evidence session per run. These producers
write an initial atomic failed receipt before any browser, model, or host work,
then overwrite it only after their exact source hashes and checks pass:

- `test-source-clock.cjs`
- `browser.cjs`
- `background-ui.cjs`
- `analysis-browser.cjs`
- `compare-native-mdx.py`
- `verify-mdx-downstream.cjs`
- `verify-native-inference-profile.py`
- `verify-native-game.py`
- `qa/restore-preview/browser.cjs` when
  `LIGHTFORGE_RESTORE_QA_OUTPUT=qa/release-2.4.2`

`verify-analysis.py` requires every session-bound receipt to carry the same
valid evidence-session nonce, to pass cleanly, and to bind exactly the source
bytes consumed by that producer. A stale, missing, mixed-session, or
source-mismatched receipt blocks verification.

The downstream MDX producer checks its same-session upstream receipt before
reading model assets. A missing, failed or foreign-release upstream receipt
therefore replaces any stale downstream pass with a failure even when model
graphs have not been installed locally.

The native GAME producer executes the actual production `NativeGame.java` engine
and the shipped WASM adapter with the unchanged original graphs, eight diffusion
steps, production 12-second cores, two-second context and deterministic seeds.
It covers the complete public demo and the independently licensed seven-second
Falcon mixture. Both inputs use the production WAV reader and identical float32
channel averaging; this direct transcription comparison does not run separation.

Final transcription through the actual production `game.process` stitching path
and native-checkpoint resume must match the WASM output. Retained unrounded notes
preserve numerical differences; internal native tensors are not observed, and
this gate makes no claim of exact tensor parity or physical-device speedup.
The analysis gate replays the retained notes rather than trusting a success flag.
Android native execution and lifecycle instrumentation remain separate gates.

## Historical anchors

The 2.2.4 native runtime comparison and the initial/revised MDX failure
artifacts remain under `qa/release-2.2.4/`, byte-for-byte. They are immutable
historical context only. The 2.4.2 verifier never treats their source hashes or
version metadata as evidence that current 2.4.2 code ran.

The fresh MDX run preserves the prior failure paths and hashes in its receipt,
while the new source helpers and all current browser/background results are
bound to the 2.4.2 session. Do not copy prior receipts or generated outputs into
this directory.
