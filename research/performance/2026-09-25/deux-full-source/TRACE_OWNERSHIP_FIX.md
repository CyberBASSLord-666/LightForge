# Keep each passage's profiler files in its own directory

The first complete-source CPU attempt stopped at profiled passage index 4.
The plain run completed all twelve passages; the profiled run committed only
four passage receipts. Its shared active-trace directory contained 54 files:
27 current files and 27 byte-identical copies of already retained passage-003
traces. Twenty-five of those prior copies preserved their original nanosecond
mtime; all 27 shared one later ctime. This establishes stale prior-passage
copies in the pool, but does not establish which component recreated them.
The failed evidence remains unchanged and unqualified.

The research observer now supplies a newly created, passage-specific output
directory when each session starts profiling. It does not move completed traces.
A late write through an earlier session's path remains attached to that earlier
passage and cannot be collected as part of the next passage.

The original application code, model weights, session lifetime, graph calls,
input contexts and numerical operations are unchanged. The isolated observer
uses `DeuxSourceTrace`, which rejects unknown or repeated graph-prefix requests.
Each completed passage records exactly 27 named trace hashes. After the JVM
exits, the collector rechecks every recorded hash and the exact graph inventory;
its original 335-call/provider checks and exact plain/profiled Float32 comparison
remain mandatory. Extra, missing, changed or misplaced files cause rejection.

Focused regressions exercise the actual Java helper without model inference:
two successive passages own different paths, a late prior-passage rewrite does
not enter the next passage, and duplicate prefixes or extra files fail. Python
tests additionally reject a modified earlier trace during the final receipt-bound
recheck. CPU compilation and the pinned runtime probe pass. A fresh, committed
source execution is still required to qualify all 24 predictions and the
production consumer; these tests do not rescue the failed attempt.
