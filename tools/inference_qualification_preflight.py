#!/usr/bin/env python3
"""Check runner eligibility without changing CPU controls or qualifying a model.

The actual benchmark and build verifier remain the release authorities. This
read-only check explains unsupported runners before downloads and conversion.
It does not manufacture missing cgroup observations or replace any measurement.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import platform
import sys

_SPEC = importlib.util.spec_from_file_location(
    'inference_preflight_benchmark', Path(__file__).with_name('benchmark_deux_parallel.py'))
benchmark = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(benchmark)


REQUIRED_COUNTERS = {
    'cgroupCpuStat': ('throttled_usec',),
    'cgroupMemoryEvents': ('oom', 'oom_kill', 'max'),
    'cgroupMemoryStat': ('pgscan_direct', 'pgsteal_direct'),
}


def inspect_runner():
    record = {
        'schema': 'lightforge.inference-runner-preflight.v1',
        'eligible': False,
        'qualificationEstablished': False,
        'scope': 'Read-only host eligibility, not inference or release qualification.',
        'platform': platform.system(),
        'architecture': platform.machine(),
    }
    try:
        if record['platform'] != 'Linux' or record['architecture'] not in {'x86_64', 'AMD64'}:
            raise ValueError('The pinned host benchmark requires Linux x86_64')
        # Reuse the benchmark's exact affinity and finite-quota requirements.
        # No process affinity, quota, mount or system setting is changed here.
        record['hostControls'] = benchmark.child_cpu_control()
        counters = benchmark.b.host_counters()
        for group, names in REQUIRED_COUNTERS.items():
            values = counters.get(group)
            for name in names:
                value = values.get(name) if isinstance(values, dict) else None
                if type(value) is not int or value < 0:
                    raise ValueError('Required cgroup-v2 observation is unavailable or invalid: '
                                     + group + '.' + name)
        record['observedCounters'] = {
            group: {name: counters[group][name] for name in names}
            for group, names in REQUIRED_COUNTERS.items()
        }
        record['eligible'] = True
    except (OSError, ValueError, KeyError, TypeError) as error:
        record['reason'] = str(error)
        record['requiredRunner'] = (
            'An existing isolated Linux x86_64 runner with at least eight allowed '
            'CPUs, a readable finite cgroup-v2 CPU quota of at least eight CPUs, '
            'and the required CPU throttling, OOM and direct-reclaim counters. '
            'Missing observations cannot be treated as zero.'
        )
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional diagnostic JSON, never release evidence')
    args = parser.parse_args()
    record = inspect_runner()
    output = json.dumps(record, indent=2) + '\n'
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding='utf-8')
    print(output, end='')
    if not record['eligible']:
        print('Inference qualification blocked: ' + record['reason'] + '\n'
              + record['requiredRunner'], file=sys.stderr)
    return 0 if record['eligible'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
