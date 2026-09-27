# Original-model acceleration research evidence

These JSON receipts preserve the September 20, 2026 diagnostics from research
commit `041d0099d58b8867ad8d6d08d194cbb185798256`. Their source hashes bind the
executed tools and original model/runtime/input identities. JSON whitespace was
compacted for storage; receipt values are unchanged.

- `deux-operator-profile.json`: all 27 graphs and 335 calls; complete profiled and
  unprofiled public-demo outputs matched byte-for-byte. Raw host event durations
  identify matrix multiplication, layout and elementwise work; they do not
  establish GPU device time or an optimization's speedup.
- `deux-cpu-controls.json`: production CPU/ALL and CPU/BASIC plus their profiled
  twins. Observers matched exactly; optimization settings changed Float32 samples.
  Numerical equivalence is unproven, without an inferred musical-quality verdict.
  Inputs and 96 compiled snapshot/class hashes were rechecked after qualification.
- `cuda-readiness.json`: original inputs and pinned runtime were inspected;
  unavailable NVIDIA hardware prevented GPU execution.

No receipt establishes a 75% reduction, whole-song or Android speedup, musical
quality approval, or publication readiness. The CPU controls are individual
diagnostics, not repeated timing ratios. Private phone logs, private audio,
credentials, model weights and raw Float32 audio are not stored in this directory.

The full trace/output archive was generated with SHA-256
`b46c5295623a8b255f5068c5efc0efe393556125942220a1567484dc273009e2`, but its
separate persistent file transfer failed. Do not assume that archive is durably
available; these receipts and the committed tools preserve the findings and
their reproducible source bindings. Regenerate public-demo traces and outputs
using the documented commands if the working archive is unavailable.

See [the acceleration plan](../../../docs/75_PERCENT_ACCELERATION_PLAN.md) for
the stage budget, complete vocal-stage work, qualification path and commands.
