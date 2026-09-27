#!/usr/bin/env python3
"""Read preserved diagnostics; no inference, timing admission, or quality approval."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import zipfile

PINS = {
    "game-deterministic": {
        "archiveBytes": 30318186,
        "archiveSha256": "7824b02e6f91c36574c27ff9dc7d34d8c0230cd47a88db96c00acf59d4aac66a",
        "receiptSha256": "d4a144b779b886a3b675ae0dfbf3e43160d6b5a4a7da9084951c42a016a2dc33",
        "sourceCommit": "9ca73bb8681434f6f2dc9ce1a00ce33531a04379",
        "graphs": 5, "calls": 12,
    },
    "deux-t4": {
        "archiveBytes": 50841267,
        "archiveSha256": "87e4e7010c62db52b30ea881d18b62ae3e5c93a415db618ca184ddab6041be47",
        "receiptSha256": "c69c686bfc312cb77443c70fd2ebb957ce668b781f543cf7bd3debafd6e6c025",
        "sourceCommit": "8590ac4a67de4340857a96ffe38bae53d7d902b8",
        "graphs": 27, "calls": 335,
    },
}
VARIANTS = ("cpu_all", "cpu_basic", "gpu_package_cpu_basic", "cuda_basic")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def analyze(path, name):
    pin = PINS[name]
    assert path.stat().st_size == pin["archiveBytes"]
    assert sha(path.read_bytes()) == pin["archiveSha256"]
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert len(names) == len(set(names))
        receipt_name, = [n for n in names if n.endswith("/qualification/receipt.json")]
        receipt_bytes = archive.read(receipt_name)
        assert sha(receipt_bytes) == pin["receiptSha256"]
        receipt = json.loads(receipt_bytes)
        assert receipt["status"] == "NUMERICAL_EQUIVALENCE_UNPROVEN"
        assert not any(receipt[f] for f in ("measured", "qualityApproved", "target75Proven", "releaseAuthorized"))
        root = receipt_name.rsplit("/", 1)[0] + "/"
        variants = []
        for variant in VARIANTS:
            game = name == "game-deterministic"
            run, = [r for r in receipt["runs"] if (r["variant"] == variant and r.get("mode") == "profiled")
                    or (not game and r["variant"] == variant + "_profiled")]
            prefix = root + variant + ("_traces/" if game else "_profiled_traces/")
            files = [n for n in names if n.startswith(prefix) and n.endswith(".json")]
            bound = {row["traceFile"]: row for row in receipt["providerTraces"][variant]["graphs"]}
            assert len(files) == len(bound) == pin["graphs"]
            graphs = []
            operators = collections.defaultdict(lambda: [0, 0])
            for filename in sorted(files):
                raw = archive.read(filename)
                binding = bound[filename.rsplit("/", 1)[-1]]
                assert len(raw) == binding["traceBytes"] and sha(raw) == binding["traceSha256"]
                events = json.loads(raw)
                counters = collections.Counter()
                durations = collections.Counter()
                for event in events:
                    if event.get("ph") != "X":
                        continue
                    elapsed = event["dur"]
                    assert isinstance(elapsed, (int, float)) and elapsed >= 0
                    if event.get("cat") == "Session":
                        counters[event["name"]] += 1
                        durations[event["name"]] += elapsed
                    if event.get("cat") == "Node" and event.get("name", "").endswith("_kernel_time"):
                        args = event["args"]
                        item = operators[args["provider"], args["op_name"]]
                        item[0] += 1
                        item[1] += elapsed
                assert counters["session_initialization"] == counters["model_loading_uri"] == 1
                assert counters["model_run"] == binding["modelRuns"]
                graphs.append({"graph": binding["graph"], "traceFile": filename,
                               "traceSha256": binding["traceSha256"], "counts": dict(counters),
                               "hostDurationUs": dict(durations)})
            totals = {key: sum(g["hostDurationUs"].get(key, 0) for g in graphs)
                      for key in ("model_loading_uri", "session_initialization", "model_run", "SequentialExecutor::Execute")}
            assert sum(g["counts"]["model_run"] for g in graphs) == pin["calls"]
            ranked = [{"provider": p, "operator": op, "calls": count, "hostDurationUs": us}
                      for (p, op), (count, us) in sorted(operators.items(), key=lambda pair: (-pair[1][1], pair[0]))]
            row = {"variant": variant, "profiledPassageWallNanos": run["wallNanos"],
                   "profiledProcessWallNanos": run["processWallIncludingStartupAndInspectionNanos"],
                   "graphCount": len(graphs), "modelRunCount": pin["calls"],
                   "ortHostDurationUs": totals, "graphs": graphs,
                   "topHostKernelEvents": ranked[:10],
                   "explicitHostCopyEvents": [r for r in ranked if "memcpy" in r["operator"].lower()]}
            if game:
                row["capturedJavaRunSeconds"] = run["capturedGraphInferenceSeconds"]
            else:
                profile_name = root + variant + "_profiled/diagnostic-0.profile.txt"
                profile_bytes = archive.read(profile_name)
                assert sha(profile_bytes) == run["profileSha256"]
                records = [dict(part.split("=", 1) for part in line.split())
                           for line in profile_bytes.decode().splitlines()]
                row["javaProfileSha256"] = sha(profile_bytes)
                row["javaStageWallMs"] = {r["stage"]: {"samples": int(r["samples"]), "wallMs": int(r["wallMs"])}
                                          for r in records if r["schema"] == "native-inference-stage-v1"}
                graph_records = [r for r in records if r["schema"] == "native-inference-graph-v2"]
                row["javaGraphSumsTruncatedWallMs"] = {
                    key: sum(int(r[key]) for r in graph_records if r[key] != "unavailable")
                    for key in ("modelPrepareWallMs", "sessionInitWallMs", "tensorBindWallMs", "runWallMs")}
            variants.append(row)
    return {"experiment": name, "pins": pin, "variants": variants}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-directory", type=Path, required=True,
                        help="Contains game-deterministic.zip and deux-t4.zip")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), "Refusing to replace an analysis"
    result = {
        "schema": "lightforge.cold-session-overhead-analysis.v1",
        "evidenceCommit": "d1c6a853fb5ee6df7cb4fa6f751988c66b5158a8",
        "method": "Re-read digest-pinned preserved ZIPs and primary receipts; recompute named host events from every profile trace.",
        "experiments": [analyze(args.archive_directory / (name + ".zip"), name) for name in PINS],
        "measuredSteadyState": False, "qualityApproved": False, "target75Proven": False,
        "limitations": [
            "One profiled cold passage per control; no repeated uninstrumented timing or accepted speed ratio.",
            "ORT event durations are host observations, not CUDA device timings or removable critical-path costs.",
            "Each graph trace has its own timestamp origin. Cross-file intervals are not merged into a global timeline.",
            "model_run contains SequentialExecutor and kernel events; these totals must not be added.",
            "Java model-init/run spans enclose ORT spans; Java and ORT totals must not be added.",
            "The Java profile reports truncated milliseconds; sums of per-graph values can differ from aggregate stage values.",
            "Explicit copy nodes do not account for every transfer, synchronization, allocator, or output-binding cost.",
            "Model/session persistence would require new lifecycle and resource qualification; no measured savings are inferred.",
            "Public mixture GAME and one Deux passage do not establish full-song quality or whole-vocal-stage performance.",
        ],
    }
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
