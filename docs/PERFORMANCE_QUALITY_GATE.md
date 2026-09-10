# Performance quality gate

`tools/performance_quality_gate.py` compares repeated baseline and candidate runs under a policy whose tolerances are committed before measurement. It emits machine-readable JSON and fails closed on missing required metrics, missing locked tracks, or any critical regression.

Input reports use `{"runs":[{"track_id":"...","metrics":{...}}]}`. Include repeated runs for every track. Nested metric names are flattened with dots. Run:

```sh
python3 tools/performance_quality_gate.py --baseline baseline.json --candidate candidate.json --policy qa/performance-gate-policy.json --output quality-gate-report.json
```

`PASS_TARGET` means the median per-track runtime reduction reaches 75% with no critical regression. `PASS_PARTIAL` preserves validated improvements but is deliberately not production-ready. `FAIL` blocks release. Populate `required_tracks` with the immutable IDs of the licensed local corpus before treating the gate as a release control; audio and copyrighted material must remain outside the repository.

The default critical set covers vocal alignment, beat/downbeat accuracy, bass events, structural recall, high-salience coverage, perceptual synchronization, actuator feasibility, and high-salience collision loss. Tolerances must be changed in a separate, reviewed commit before candidate results are generated.
