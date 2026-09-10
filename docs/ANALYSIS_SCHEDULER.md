# Analysis scheduler

`web/analysis/scheduler.js` admits only one complete heavy analysis pipeline at a time. This is intentional: one pipeline owns large WASM/native inference heaps and durable OPFS checkpoints, so concurrent pipelines increase memory and checkpoint-write risk without improving a single show.

The scheduler is FIFO within a document. When the browser implements the Web Locks API, it also holds the origin-wide `lightforge-analysis-heavy-v1` exclusive lock until the job releases it, preventing competing LightForge tabs from running heavy model heaps concurrently. A missing or broken optional Web Locks implementation falls back to the local gate; it never changes model selection, inputs, stage order, precision, or outputs.

Each granted lease exposes a bounded, privacy-safe diagnostics object:

- `schemaVersion`
- `resourceClass` (`analysis-heavy`)
- `capacity` (currently one, pending measured native-memory evidence)
- `crossContextMode`
- `waitMs`
- `admissionTicket`

No audio path, project ID, cache key, lyric, or model payload is placed in scheduler diagnostics. A queued job can be cancelled before admission without touching its existing checkpoint. The caller must always release a granted lease in `finally`; release is idempotent and waits for the cross-tab lock to be relinquished before the next local job starts.

The interactive studio (`web/index.html`) and service-owned background runner (`web/background/runner.html`) both load this module before `analysis/analyzer.js`. If a background WebView does not expose Web Locks, the scheduler records `single-context` for that run and preserves the established one-job service ownership.
