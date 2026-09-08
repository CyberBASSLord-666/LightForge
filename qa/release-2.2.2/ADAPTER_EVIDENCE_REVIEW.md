# 2.2.2 numerical evidence and adapter review

This version-specific check retains the numerical measurements of the exact
2.2.1 kernels and model graphs. It does not call the changed pipeline a fresh
numerical benchmark. Current complete-browser analysis and Android lifecycle
execution remain mandatory independently.

## Immutable predecessor

The files under `prior-source/` were fetched from the 2.2.1 candidate commit
`f80de0d7fd075cf22506c60910e41ea9f625e922`, also bound by the published release
request. Their Git blob identities were checked after saving:

| Original path | Git blob |
| --- | --- |
| `qa/release-2.2.1/analysis-verification.json` | `659a6f6a393fcc4aeb82737ec4768c4e4d5ccada` |
| `web/analysis/ASSET_MANIFEST.json` | `308922642ae21d789659867cd093edc7956de57b` |
| `web/analysis/analyzer.js` | `cc930c3a58247e31807d9c2ea67a7415d1695169` |
| `web/analysis/worker.js` | `1546931a7a252982d3401b10d601d5b322107af6` |

The verifier pins their full SHA-256 values, the exact current manifest and the
exact before/after adapter bytes. It rejects any different future change. The
prior version metadata has separate [provenance](PRIOR_VERSION.md).

## Reviewed adapter differences

- `analyzer.js` adds optional diagnostics at stage start/end and progress, logs
  native callback errors, carries a bounded worker error stack into the error
  object, and explicitly rejects a worker message that cannot be deserialized.
  The four-stage ordering, source reads, native passage offsets, model options,
  checkpoint identity, successful results and numerical algorithms are unchanged.
- `worker.js` bounds its existing failure message to 3072 characters and includes
  an optional stack capped at 8192 characters. The import list, models, transforms,
  inference calls, returned successful arrays and resource cleanup are unchanged.

These diagnostic and failure-handling changes require runtime verification:
logging can affect execution overhead, and message-error handling is new
behavior. Retaining kernel measurements does not prove either behavior. The
current `analysis-browser-verification.json` and
`android-background-verification.json` must pass before release packaging.

Every directly bound source in the original numerical receipt, including
`NativeDeux.java`, `NativeDeuxTransform.java`, GAME, separation, DSP and the
reference test sources, must still match its original SHA-256. All 73 current
analysis assets are checked against their exact manifest, and the only allowed
manifest differences are the two explicitly reviewed adapters. This protocol
cannot bless changed kernels, graphs, arbitrary manifest entries or further
adapter edits. Historical receipts are preserved intact.

The receipt preserves every original directly measured file under
`source_hashes`. The complete 73-file analysis inventory is additionally
reported under `analysis_asset_hashes`; generated graphs are verified in full
during this gate without adding checkout requirements for files excluded from
Git. The exact outer and model manifests remain source-bound, and publication
independently verifies every delivered APK asset against those manifests.
