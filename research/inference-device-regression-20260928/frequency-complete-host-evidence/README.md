# Controlled combined frequency host qualification

The exact current-source benchmark completed one warmup pair and three measured
AB/BA/AB pairs through all 27 original graphs. Its eight complete outputs were
finite and bit-identical to the original demo reference:
`d9cd80a15c19921b2f472233a4a3bb86eec3e39aef66374a9c007b4b9efc5837`.
Baseline profiles contain 335 calls. Eight-worker candidate profiles contain
1,727 calls with full temporal context and independent B16 frequency frames.

Measured median whole-passage wall time fell from 47.838871175 to 22.687393368
seconds, a 52.5753998563% reduction. Individual measured pair reductions were
57.3944803888%, 51.3800256262%, and 51.6388393593%. Median process CPU time fell
from 144.70 to 123.47 seconds. These figures were independently recalculated
from the raw run records at archive time.

Every child used the same seven observed CPUs, leaving one CPU of host quota
reserved. No measured interval increased cgroup OOM, memory-limit, or direct
reclaim counters; observed throttle-to-wall ratio was zero. Median whole-process
peak RSS increased from 854,720,512 to 1,079,443,456 bytes. The candidate's memory
cost is not hidden and no production memory threshold was reduced. The original
15% median / 5% each-pair / 5% throttle criteria all passed unchanged.

Original receipt, wrapper/run/compile logs, all eight exact profiles, frozen
source text and compiled-class hash inventory are preserved. `archive.json`
records independent timing/resource recomputation, source/class/profile linkage,
and complete output size/hash/finiteness checks. PCM and executable/model
binaries are omitted; no inference was rerun to create this archive. The exact
published receipt is `../frequency-complete-host-qualification.json`.

This qualifies a fixed execution configuration on the host. It does not prove
physical-phone admission, sustained adaptive-policy behavior, net benefit after
qualification cost, or full-song/end-to-end improvement. The source-bound
production build gate remains held for the changed NativeDeux source; version
2.4.1 / 20401 is unchanged and no production release has been built.
