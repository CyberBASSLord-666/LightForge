# Performance research checkpoint — September 25, 2026

The 75% complete-analysis time reduction is **not proven**. No application or
release change is approved by this research checkpoint.

## Verified result

[GAME CPU session reuse](session-reuse/RESULTS.md) passed the complete public
64-second mixture diagnostic: all 96 captured tensor pairs and unrounded notes
match, and the unchanged production consumer produces the same 98 final notes
with exact checkpoint recovery. Six fresh JVMs cover default and retained
session lifetimes with plain, captured and profiled observers. Evidence is
durable at commit `69ac443a90e8a0257c1f4d309af651ff33ac8acf`.

This result does not establish GPU parity, actual separated-vocal behavior,
general musical quality, Android lifecycle behavior or a speed ratio.

## Full-source separation remains blocked

The first full-source Deux attempt is preserved under
[blocked-20260925-01](deux-full-source/blocked-20260925-01/README.md), in commit
`922f13fc99ee1aede6f40e3c689bc89dc5365e21`. It completed twelve plain and four
profiled passage receipts, then rejected extra copies of prior-passage traces.

The [passage-owned trace observer](deux-full-source/TRACE_OWNERSHIP_FIX.md) was
reviewed, tested and frozen at `925fc91ecb198141901ef62eb55feb7d7e43c3a0`.
Its fresh second attempt completed all twelve plain predictions, then stopped
at an exact output inventory check before profiling began. Eleven unexpected
temporary files remained beside completed stems; ten contain byte-identical
copies of the vocal half of their final output and one is empty. The mechanism
that recreated them is unproven. Neither failed run is a qualified complete
diagnostic; no downstream separated-voice inference has started.

The second attempt is retained under
[blocked-20260925-02](deux-full-source/blocked-20260925-02/README.md). A bounded
[rename probe](filesystem-rename-probe/README.md) did not reproduce the behavior
in either the workspace or `/tmp`; it establishes no workaround.

Keep the original sources and strict gates unchanged. Investigate temporary
file ownership and execution storage before another fresh full-source attempt.
Do not delete unexpected files to make an old run pass.

## Prepared downstream reference

The [GAME-on-separated-voice workflow](game-separated-voice/README.md) is frozen
at `088ca835fafba971662285795bae1ac49524c3e3`. It requires and repeats a successful
independent full-source Deux audit before deriving any input. It preserves the
actual production voice PCM, five original graphs, eight diffusion steps and
six original windows/seeds, then runs three default-lifetime CPU JVMs and the
production checkpoint consumer. Input and auditor tests and independent review
passed; actual inference remains pending upstream qualification.

## GPU continuation

Colab sign-in initially returned HTTP 502. A later browser reload reached
Google's account chooser. Before the secure account-selection request could be
issued, the browser inspection timed out; one lighter recovery check also timed
out. No secure request was submitted and authentication is not verified. No available
Colab/Kaggle plugin was found in the current plugin-directory search. No new
GPU inference was performed in this checkpoint.

The existing full-source Deux collector can execute CPU/CUDA, but this day's
local driver, exporter and independent auditor are CPU-only. A GPU run needs a
separate reviewed wrapper and CUDA-aware audit, followed by GAME on each arm's
actual separated voice. Historical single-passage notebooks and mixture GAME
evidence cannot substitute for that chain.

Even that chain excludes full vocal classification/fusion, accompaniment bass,
rhythm/structure, timeline and show compilation. Comparable repeated timing of
the complete path, including transfer and persistence, and the approved corpus
and policy gates are still required before a 75% claim.
