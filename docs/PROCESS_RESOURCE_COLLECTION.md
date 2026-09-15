# External workload resource collection

`tools/collect_process_resources.py` launches the actual supplied Linux command.
It records its complete command window, including setup and teardown. It does
not substitute the Python collector's CPU consumption for the workload's CPU,
and it does not call that whole window application-only analysis time.

The receipt always states `release_qualified: false`. This tool supplies a
resource acquisition component; it does not supply musical scores, blinded
review, approved benchmark inputs, or the complete release diagnostic schema.

Run a real workload:

```bash
python3 tools/collect_process_resources.py \
  --output /private/new-resource-observation.json \
  --timeout 3600 --interval 0.1 \
  -- python3 -c 'sum(i*i for i in range(5000000))'
```

This executes a small CPU workload. For app measurement, replace that command
with the actual installed application capture runner and its required arguments.
Command arguments, environment, input paths, stdout and stderr are excluded
from the receipt; workload stdout/stderr are sent to `/dev/null`. Workload
outputs should be written by the workload itself to its separate private
output directory. Existing receipt files are never overwritten.

To wrap the implemented application capture, first prepare the approved WAV,
web lock, identity and configuration using `qa/locked-benchmark/CAPTURE.md`:

```bash
python3 tools/collect_process_resources.py \
  --output /private/capture/candidate-pair-01-resources.json \
  --timeout 4000 --interval 0.1 \
  -- node qa/locked-benchmark/capture-app.cjs capture \
     --app-root /absolute/candidate-source \
     --wav /private/approved-audio/input.wav \
     --audio-sha256 ACTUAL_PREAPPROVED_WAV_SHA256 \
     --web-manifest /private/capture/web-lock.json \
     --identity /private/capture/candidate-identity.json \
     --configuration /private/capture/analysis-configuration.json \
     --output-dir /private/capture/candidate-pair-01 \
     --timeout-seconds 3600
```

The resource wrapper measures the entire command, including inventory checks,
browser startup, analysis, compilation, serialization and teardown. Its resource
window must not be spliced into the capture's narrower analyzer-only timer.
For complete process-tree counters add the explicitly delegated `--cgroup-parent`
before `--`; without it this invocation deliberately reports partial accounting.

Without a delegated cgroup, `accounting_scope` is `root-process-incomplete`.
The tool samples the root's `/proc` RSS and block-I/O counters and obtains that
child's actual `wait4` CPU/RSS statistics. `wait4` may include descendants the
root reaped, but cannot prove complete process-tree coverage. Short-lived I/O
may escape sampling. This mode never emits a gate contract projection.
If the host restricts child `/proc` I/O, that byte domain remains absent while
the independent RSS and kernel `wait4` input/output block counts are retained.
Raw block counts are not relabeled as measured bytes.

For complete process-tree accounting, the benchmark host administrator can
delegate a cgroup-v2 domain and its CPU, memory and I/O controllers. Pass its
existing directory through `--cgroup-parent`. The collector creates a fresh
empty child and moves only its own newly launched process into it before exec.
It never changes parent controller settings or moves existing processes.
Frozen groups are rejected before launch. A constant isolated Python bootstrap
attaches itself before execing the supplied workload; pre-attachment bootstrap
CPU is excluded from cgroup counters and identified as such. Attachment runs
after `Popen` returns, so even a concurrent freeze remains under the timeout.
Normal completion waits for the new cgroup to become empty; timeout and
cancellation kill only that cgroup and the collector's own new process group.
Cleanup is bounded and failures are explicit.
The process group is signaled only while its leader remains an owned, unreaped
child, so its numeric PID/PGID cannot have been reused. Once that leader is
reaped, remaining descendants are targeted only through a still-populated owned
cgroup. Successful empty cgroups receive no kill operation. Fallback mode checks
root exit with `waitid(WNOWAIT)` and cleans same-session descendants before
reaping the leader. Unreadable population state remains an explicit cleanup
failure and never authorizes signaling a stale process-group identifier.

The cgroup records raw `cpu.stat` usage, `memory.peak` and `io.stat` counters.
`memory.peak` includes charged cache/kernel memory and is explicitly **not RSS**;
it is not silently mapped to the gate's peak-RAM metric. CPU capacity is the
attached bootstrap's actual `sched_getaffinity` count, returned through a bounded
private pipe before workload exec. A delegated cgroup's narrower cpuset changes
that measured denominator; the collector parent's affinity is not substituted.
This is not a quota-adjusted utilization denominator. The
approved runtime profile must fix quotas/cpuset and forbid workload migration
or changed affinity during collection. This is observational instrumentation,
not a sandbox for malicious commands with authority over the host/cgroup tree.

Optional approved sensors:

```text
--energy-counter <readable cumulative-microjoule-counter>
--energy-counter-id <approved-opaque-id>
--thermal-sensor <readable-millicelsius-counter>
--thermal-sensor-id <approved-opaque-id>
```

Energy is explicitly host-package scope, not process-attributed energy. Use an
isolated, approved benchmark host; unrelated host activity contributes to the
counter. No power estimate or zero substitutes for an unavailable sensor.
Negative energy deltas, resets, wraps, unreadable/malformed samples, excessive
sample counts and nonmonotonic sampling invalidate that sensor domain. Thermal
samples retain observed temperatures; endpoints span the recorded window.
Counter reads are sequential at the window boundaries, which the receipt
records. Select a sampling interval appropriate to the sensor update rate.
FIFO/device inputs are rejected with nonblocking open and regular-file checks,
so a mistaken sensor path cannot stall collection before the workload starts.

On successful complete cgroup execution, `contract_projection.execution`
contains the external-workload CPU/wall observations and raw
`lightforge-resource-counters-v1` CPU/energy/thermal fields. The projection is
only an input to a future synchronized stage/report adapter. It must not be
spliced into a different app-only timing window. Allocation, temporary storage
and accelerator observations remain unobserved, and absent energy/thermal
still block release qualification under the unchanged policy.

The CLI returns success for a completed zero-exit workload even when accounting
is partial; consumers must inspect the explicit coverage fields. A cgroup
requested but unavailable fails before executing the workload. No fallback
silently changes the requested accounting scope.

Verification:

```bash
python3 -m unittest discover -s tests -p 'test_collect_process_resources.py'
```

Tests include real external CPU and fsynced-I/O work, nonzero exit, bounded
timeout with descendant cleanup, signal cancellation, privacy, sensor reset,
invalid counter tables and overwrite rejection. Mock cgroup reads test mapping
only; they are not claimed as a hardware/cgroup benchmark.
