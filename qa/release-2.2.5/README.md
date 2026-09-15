# LightForge 2.2.5 verification source protocol

This directory contains the source helpers for a fresh 2.2.5 verification run.
It intentionally contains no receipts, logs, screenshots, retained model outputs,
or prior release results.

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
- `qa/restore-preview/browser.cjs` when
  `LIGHTFORGE_RESTORE_QA_OUTPUT=qa/release-2.2.5`

`verify-analysis.py` requires every session-bound receipt to carry the same
valid evidence-session nonce, to pass cleanly, and to bind exactly the source
bytes consumed by that producer. A stale, missing, mixed-session, or
source-mismatched receipt blocks verification.

## Historical anchors

The 2.2.4 native runtime comparison and the initial/revised MDX failure
artifacts remain under `qa/release-2.2.4/`, byte-for-byte. They are immutable
historical context only. The 2.2.5 verifier never treats their source hashes or
version metadata as evidence that current 2.2.5 code ran.

The fresh MDX run preserves the prior failure paths and hashes in its receipt,
while the new source helpers and all current browser/background results are
bound to the 2.2.5 session. Do not copy prior receipts or generated outputs into
this directory.
