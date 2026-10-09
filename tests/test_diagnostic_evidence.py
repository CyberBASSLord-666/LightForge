"""Observation boundaries and privacy tests for Android diagnostic summaries."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("diagnostic_evidence", ROOT / "tools/diagnostic_evidence.py")
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)
BASE = datetime(2000, 1, 1, tzinfo=timezone.utc)


def event(seconds, tag, message, level="INFO"):
    stamp = (BASE + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return f"{stamp} {level} {tag} {message}"


def report(*events):
    return "\n".join((
        "LIGHTFORGE DIAGNOSTIC REPORT", "Format: 1 (UTF-8)",
        "CURRENT ENVIRONMENT", "app=com.cyberbasslord.lightforge version=2.2.5 code=20205",
        "manufacturer=example model=synthetic sdk=37 android=17 cpuCores=8",
        "webview=com.google.android.webview 154.0.8037.22",
        "batteryExempt=true backgroundRestricted=false heapLimitBytes=536870912",
        "CURRENT ANALYSIS JOB", "jobRef=PRIVATE_JOB_IDENTIFIER", "state=completed",
        "elapsedMs=12000", "restoredStages=2", "analysisQuality=precision",
        "ANDROID PREVIOUS PROCESS EXITS", "description=PRIVATE_EXIT_DESCRIPTION",
        "PERSISTENT EVENT TRACE (oldest to newest)", *events, "END OF DIAGNOSTIC REPORT", "",
    ))


def profile(seconds, *, wall="100", inference="90", outcome="completed", graph_count=1, details=True,
            cpu_telemetry="unavailable", instrumented_cpu="unavailable"):
    lines = [event(seconds, "native-inference-profile",
                   f"schema=native-inference-profile-v2 outcome={outcome} wallMs={wall} inferenceWallMs={inference} "
                   f"waitWallMs=0 instrumentedCpuMs={instrumented_cpu} cpuTelemetry={cpu_telemetry} "
                   f"acceleratorTelemetry=unavailable stageRecords=1 graphRecords={graph_count} "
                   "droppedStageRecords=0 droppedGraphRecords=0 cacheModelHits=1 cacheModelMisses=0 "
                   "PRIVATE_FIELD=PRIVATE_PROFILE_TEXT")]
    if details:
        lines += [event(seconds + .001, "native-inference-profile",
                        "schema=native-inference-stage-v1 stage=inference samples=1 wallMs=90 cpuMs=unavailable"),
                  event(seconds + .002, "native-inference-profile",
                        "schema=native-inference-graph-v2 graph=front runCount=1 runWallMs=90 runCpuMs=unavailable")]
    return lines


def policy_records(*, pairs=3, seeded=False, recheck=False):
    records = [
        "schema=native-passage-policy-v1 state=qualified workers=4 reason=measured-passage-improvement "
        "extraNanos=22000000000 extraCapNanos=360000000000 projectedAccruedSavingsNanos=123000000000 "
        f"qualificationPairs={pairs} currentJobPairs={0 if seeded else pairs} seeded={str(seeded).lower()} "
        "activePassages=7 leasePassages=8 paybackScope=projected-not-measured"
    ]
    for index in range(pairs + int(recheck)):
        repeated = index == pairs
        records.append(
            "schema=native-passage-pair-v1 "
            f"role={'recheck' if repeated else 'qualification'} index={0 if repeated else index} ordinal={index + 1} "
            f"candidateFirst={str(index % 2 == 0).lower()} workers=4 baselineNanos=10000000000 "
            "candidateNanos=8000000000 extraNanos=9007199254740993 outputSha256=" + "a" * 64 +
            " finite=true exact=true fullGeometry=true coldSessions=true"
        )
    return records


def alternate_policy_records(pairs=3):
    records = [
        "schema=native-passage-policy-v1 "
        f"state={'qualified' if pairs == 3 else 'provisional'} workers=4 "
        f"reason={'measured-passage-improvement' if pairs == 3 else 'alternate-pending' if pairs == 0 else 'qualification-pending'} "
        f"extraNanos={225000000 + pairs * 150000000} extraCapNanos=360000000000 "
        "projectedAccruedSavingsNanos=0 "
        f"qualificationPairs={pairs} currentJobPairs={pairs + 1} seeded=false "
        "activePassages=0 leasePassages=8 paybackScope=projected-not-measured",
        "schema=native-passage-pair-v1 role=rejected index=0 ordinal=0 candidateFirst=false "
        "workers=8 baselineNanos=200000000 candidateNanos=220000000 extraNanos=220000000 "
        "outputSha256=" + "a" * 64 + " finite=true exact=true fullGeometry=true coldSessions=true",
    ]
    for index in range(pairs):
        records.append(
            f"schema=native-passage-pair-v1 role=qualification index={index} ordinal={index + 1} "
            f"candidateFirst={str(index == 1).lower()} workers=4 baselineNanos=200000000 "
            "candidateNanos=150000000 extraNanos=150000000 outputSha256=" + "a" * 64 +
            " finite=true exact=true fullGeometry=true coldSessions=true"
        )
    return records


class DiagnosticEvidenceTest(unittest.TestCase):
    def test_screened_alternate_has_distinct_rejected_and_qualified_evidence(self):
        for count in range(4):
            records = alternate_policy_records(count)
            parsed = EVIDENCE._passage_policy(records, source="test")
            self.assertEqual(parsed["status"], "observed")
            self.assertEqual([pair["role"] for pair in parsed["pairs"]],
                             ["rejected"] + ["qualification"] * count)
            self.assertEqual(parsed["controller"]["qualificationPairs"]["value"], count)
        records = alternate_policy_records(3)
        encoded = "|".join(row.replace(" ", ",") for row in records)
        self.assertEqual(EVIDENCE._passage_policy(records, encoded, source="test")["status"], "observed")
        self.assertEqual(EVIDENCE._passage_policy(records, encoded.replace("workers=8", "workers=4"), source="test")["status"],
                         "invalid-or-incomplete")
        replacements = (
            (1, "role=rejected", "role=qualification"), (1, "index=0", "index=1"),
            (1, "ordinal=0", "ordinal=1"), (1, "candidateFirst=false", "candidateFirst=true"),
            (1, "workers=8", "workers=4"), (1, "exact=true", "exact=false"),
            (1, "candidateNanos=220000000", "candidateNanos=180000000"),
            (1, "extraNanos=220000000", "extraNanos=100000000"),
            (2, "ordinal=1", "ordinal=0"), (2, "workers=4", "workers=8"),
            (3, "candidateFirst=true", "candidateFirst=false"),
            (0, "currentJobPairs=4", "currentJobPairs=0"), (0, "seeded=false", "seeded=true"),
        )
        for index, old, new in replacements:
            broken = records.copy()
            self.assertIn(old, broken[index])
            broken[index] = broken[index].replace(old, new)
            self.assertEqual(EVIDENCE._passage_policy(broken, source="test")["status"],
                             "invalid-or-incomplete", (index, old, new))
        for broken in ([*records, records[1]],
                       [records[0], records[2], records[1], *records[3:]],
                       [records[0].replace("qualificationPairs=3", "qualificationPairs=2")
                        .replace("currentJobPairs=4", "currentJobPairs=3"), *records[1:-1]]):
            self.assertEqual(EVIDENCE._passage_policy(broken, source="test")["status"],
                             "invalid-or-incomplete")

    def test_unmatched_controls_remain_distinct_from_same_input_pairs(self):
        control = ("schema=native-passage-control-v1 ordinal=20 baselineNanos=75000000000 "
                   "previousBaselineNanos=75000000000 candidateMaxNanos=50000000000 candidateSamples=3 "
                   "accepted=true comparisonScope=unmatched-inputs")
        records = policy_records(recheck=True) + [control]
        records[0] = records[0].replace("reason=measured-passage-improvement", "reason=control-accepted")
        parsed = EVIDENCE._passage_policy(records, source="test")
        self.assertEqual(parsed["status"], "observed")
        self.assertEqual(len(parsed["pairs"]), 4)
        self.assertEqual(len(parsed["controls"]), 1)
        self.assertEqual(parsed["controls"][0]["candidateSamples"]["value"], 3)
        self.assertEqual(parsed["controls"][0]["comparisonScope"], "unmatched-inputs")
        self.assertIn("not-same-input", parsed["control_scope"])
        rejected = EVIDENCE._passage_policy(records[:-1] + [control.replace("accepted=true", "accepted=false")], source="test")
        self.assertEqual(rejected["status"], "observed")
        self.assertFalse(rejected["controls"][0]["accepted"])
        for broken in (records + [control], records + [records[-2]],
                       records[:-1] + [control.replace("candidateSamples=3", "candidateSamples=2")],
                       records[:-1] + [control.replace("baselineNanos=75000000000", "baselineNanos=0")],
                       records[:-1] + [control.replace("candidateMaxNanos=50000000000", "candidateMaxNanos=3600000000001")],
                       records[:-1] + [control.replace("comparisonScope=unmatched-inputs", "comparisonScope=PRIVATE")]):
            invalid = EVIDENCE._passage_policy(broken, source="test")
            self.assertEqual(invalid["status"], "invalid-or-incomplete")
            self.assertNotIn("PRIVATE", json.dumps(invalid))

    def test_v2_durable_mixed_session_counts_and_policy_keep_distinct_scopes(self):
        records = policy_records(seeded=True, recheck=True)
        text = report().replace("jobRef=PRIVATE_JOB_IDENTIFIER", "jobRef=1234567890abcdef")
        text = text.replace("ANDROID PREVIOUS PROCESS EXITS", "\n".join((
            "DURABLE ANALYSIS SUMMARIES (independent of trace rotation)",
            "schema=diagnostic-job-summary-v2 retentionJobs=3 storageBoundBytes=32768 recovery=normal",
            "jobRef=1234567890abcdef state=completed lifecycleElapsedMs=12345 durationMs=177000 analysisQuality=precision",
            " route=native-deux-v1 passages=2 completed=2 cancelled=0 otherOutcomes=0 lastTemporalConfig=cpu-i1-j1-d0-sequential-w8-b1 "
            "temporalBaselineSessionCount=3 temporalBaselineSessionCountMeasuredPassages=2 "
            "temporalFourWorkerSessionCount=0 temporalFourWorkerSessionCountMeasuredPassages=2 "
            "temporalEightWorkerSessionCount=21 temporalEightWorkerSessionCountMeasuredPassages=2 "
            "temporalUnobservedSessionCount=unavailable temporalUnobservedSessionCountMeasuredPassages=0",
            *(" " + row for row in records),
            "ANDROID PREVIOUS PROCESS EXITS",
        )))
        result = EVIDENCE.summarize(text)
        job = result["durable_job_summaries"][0]
        self.assertEqual(job["summary_schema"], "diagnostic-job-summary-v2")
        self.assertTrue(job["matches_current_job"])
        route = job["native_routes"]["native-deux-v1"]
        self.assertEqual(route["passages"]["value"], 2)
        self.assertEqual(route["metrics"]["temporalBaselineSessionCount"]["value"], 3)
        self.assertEqual(route["metrics"]["temporalFourWorkerSessionCount"]["value"], 0)
        self.assertIsNone(route["metrics"]["temporalUnobservedSessionCount"]["value"])
        self.assertEqual(route["temporal_configuration_count_scope"], "session-init-attempts-not-successful-runs")
        policy = route["passage_policy"]
        self.assertEqual(policy["status"], "observed")
        self.assertEqual(policy["timing_units"], "nanoseconds")
        self.assertEqual(policy["payback_scope"], "projected-not-measured")
        self.assertEqual(policy["controller"]["currentJobPairs"]["value"], 0)
        self.assertTrue(policy["controller"]["seeded"])
        self.assertEqual(len(policy["pairs"]), 4)
        self.assertEqual(policy["pairs"][0]["extraNanos"]["value"], 9007199254740993)
        self.assertEqual(result["qualification_status"], "not-evaluated")
        self.assertIsNone(result["full_song_runtime_ms"]["value"])
        future = text.replace("diagnostic-job-summary-v2", "diagnostic-job-summary-v3")
        self.assertEqual(EVIDENCE.summarize(future)["durable_job_summaries"], [])

    def test_policy_profile_readable_and_encoded_snapshots_are_not_extra_bundles(self):
        records = policy_records()
        encoded = "|".join(row.replace(" ", ",") for row in records)
        events = profile(0)
        events[0] += (" temporalConfigCountScope=session-init-attempts temporalBaselineSessionCount=3 "
                      "temporalFourWorkerSessionCount=9 temporalEightWorkerSessionCount=0 temporalUnobservedSessionCount=0 "
                      "passagePolicy=" + encoded)
        events.extend(event(.01 + index * .001, "native-inference-profile", row) for index, row in enumerate(records))
        result = EVIDENCE.summarize(report(*events))
        totals = result["attempts"][0]["native_profiles"]["completed_complete_bundles"]
        self.assertEqual(totals["count"], 1)
        self.assertEqual(totals["metrics"]["wallMs"]["value"], 100)
        self.assertEqual(totals["metrics"]["temporalFourWorkerSessionCount"]["value"], 9)
        self.assertEqual(totals["measurement_scopes"]["temporalConfigCountScope"], {"session-init-attempts": 1})
        self.assertEqual(len(totals["passage_policy_snapshots"]), 1)
        self.assertEqual(totals["passage_policy_snapshots"][0]["status"], "observed")
        encoded_only = EVIDENCE.summarize(report(*events[:3]))
        snapshot = encoded_only["attempts"][0]["native_profiles"]["completed_complete_bundles"]["passage_policy_snapshots"][0]
        self.assertEqual(snapshot["status"], "observed")
        # Readable and encoded copies disagree: retain observations, never bless the bundle.
        events[-1] = events[-1].replace("candidateNanos=8000000000", "candidateNanos=9000000000")
        conflict = EVIDENCE.summarize(report(*events))["attempts"][0]["native_profiles"]["completed_complete_bundles"]
        self.assertEqual(conflict["passage_policy_snapshots"][0]["status"], "invalid-or-incomplete")

    def test_failed_pairs_remain_observations_and_orphan_records_stay_unbound(self):
        records = policy_records(recheck=True)
        records[-1] = records[-1].replace("finite=true exact=true", "finite=false exact=false")
        snapshot = EVIDENCE._passage_policy(records, source="test")
        self.assertEqual(snapshot["status"], "observed")
        self.assertFalse(snapshot["pairs"][-1]["finite"])
        self.assertFalse(snapshot["pairs"][-1]["exact"])
        self.assertEqual(snapshot["qualification_status"], "not-independently-evaluated")
        result = EVIDENCE.summarize(report(event(0, "native-inference-profile", records[-1])))
        orphan = result["source"]["unassociated_passage_policy_records"]
        self.assertEqual(len(orphan), 1)
        self.assertEqual(orphan[0]["record"]["role"], "recheck")
        self.assertEqual(result["attempts"][0]["native_profiles"]["completed_complete_bundles"]["count"], 0)

    def test_policy_validation_is_bounded_private_and_keeps_missing_unknown(self):
        records = policy_records()
        for broken in (
            records[:-1], [records[0], records[2], records[1], records[3]],
            [records[0].replace("currentJobPairs=3", "currentJobPairs=4097"), *records[1:]],
            [records[0].replace("extraNanos=22000000000", "extraNanos=9223372036854775808"), *records[1:]],
            [records[0].replace("reason=measured-passage-improvement", "reason=PRIVATE_REASON"), *records[1:]],
            [records[0] + " PRIVATE_FIELD=PRIVATE_TEXT", *records[1:]],
            [records[0] + " state=qualified", *records[1:]],
            [records[0].replace(" projectedAccruedSavingsNanos=123000000000", ""), *records[1:]],
        ):
            parsed = EVIDENCE._passage_policy(broken, source="test")
            self.assertEqual(parsed["status"], "invalid-or-incomplete")
            self.assertNotIn("PRIVATE", json.dumps(parsed))
        for encoded in ("x" * 4105, "|".join([records[0].replace(" ", ",")] * 9)):
            self.assertEqual(EVIDENCE._passage_policy(encoded=encoded, source="test")["status"], "invalid")
        self.assertEqual(EVIDENCE._passage_policy(source="test")["status"], "unavailable")
        partial = EVIDENCE._policy_record(records[0].replace(" projectedAccruedSavingsNanos=123000000000", ""))
        self.assertIsNone(partial["projectedAccruedSavingsNanos"]["value"])

    def test_v1_and_partial_mixed_counts_are_never_inferred_as_zero(self):
        events = profile(0) + profile(1)
        events[0] += " temporalBaselineSessionCount=12 temporalFourWorkerSessionCount=0"
        totals = EVIDENCE.summarize(report(*events))["attempts"][0]["native_profiles"]["completed_complete_bundles"]
        self.assertEqual(totals["metrics"]["temporalBaselineSessionCount"]["status"], "partial")
        self.assertIsNone(totals["metrics"]["temporalBaselineSessionCount"]["value"])
        self.assertEqual(totals["metrics"]["temporalBaselineSessionCount"]["observed_subtotal"], 12)
        self.assertEqual(totals["metrics"]["temporalEightWorkerSessionCount"]["status"], "unavailable")
        self.assertEqual([row["status"] for row in totals["passage_policy_snapshots"]], ["unavailable", "unavailable"])

    def test_frequency_counts_preserve_missing_history_and_binding_metrics(self):
        events = profile(0) + profile(1)
        events[0] += (" frequencyConfigCountScope=session-init-attempts frequencyBaselineSessionCount=5"
                      " frequencyFourWorkerSessionCount=7 frequencyEightWorkerSessionCount=0 frequencyUnobservedSessionCount=0")
        events[2] += " tensorBindCount=1 tensorBindWallMs=2 sessionInitCount=1 modelPrepareCount=1 modelPrepareWallMs=3"
        totals = EVIDENCE.summarize(report(*events))["attempts"][0]["native_profiles"]["completed_complete_bundles"]
        self.assertEqual(totals["metrics"]["frequencyFourWorkerSessionCount"]["status"], "partial")
        self.assertIsNone(totals["metrics"]["frequencyFourWorkerSessionCount"]["value"])
        self.assertEqual(totals["metrics"]["frequencyFourWorkerSessionCount"]["observed_subtotal"], 7)
        self.assertEqual(totals["measurement_scopes"]["frequencyConfigCountScope"], {"session-init-attempts": 1, "missing-or-unknown": 1})
        self.assertEqual(totals["graphs"]["front"]["tensorBindCount"]["observed_subtotal"], 1)
        self.assertEqual(totals["graphs"]["front"]["modelPrepareWallMs"]["observed_subtotal"], 3)

    def test_parallel_profile_preserves_critical_path_and_worker_scopes(self):
        events = (
            event(0, "native-inference-profile",
                  "schema=native-inference-profile-v2 outcome=completed wallMs=170 inferenceWallMs=160 "
                  "inferenceThreadCpuMs=11 inferenceProcessCpuMs=212 inferenceCount=5 "
                  "inferenceWorkerThreadCpuMs=160 inferenceWorkerRunCount=3 inferenceWorkerCpuTelemetry=available "
                  "cpuScope=calling-thread processCpuScope=all-app-threads inferenceWallScope=critical-path "
                  "inferenceThreadCpuScope=coordinator inferenceWorkerThreadCpuScope=sum-run-calling-threads "
                  "stageRecords=1 graphRecords=1 droppedStageRecords=0 droppedGraphRecords=0"),
            event(.001, "native-inference-profile",
                  "schema=native-inference-stage-v1 stage=inference samples=4 wallMs=160 cpuMs=11 processCpuMs=212 "
                  "wallScope=critical-path cpuScope=calling-thread processCpuScope=all-app-threads"),
            event(.002, "native-inference-profile",
                  "schema=native-inference-graph-v2 graph=block-00-time runCount=3 runWallMs=240 runCpuMs=160 "
                  "runProcessCpuMs=unavailable graphWallScope=aggregate-call runCpuScope=run-calling-threads "
                  "runProcessCpuScope=unavailable-overlapping-intervals"),
        )
        totals = EVIDENCE.summarize(report(*events))["attempts"][0]["native_profiles"]["completed_complete_bundles"]
        self.assertEqual(totals["metrics"]["inferenceCount"]["value"], 5)
        self.assertEqual(totals["metrics"]["inferenceWallMs"]["value"], 160)
        self.assertEqual(totals["metrics"]["inferenceThreadCpuMs"]["value"], 11)
        self.assertEqual(totals["metrics"]["inferenceWorkerThreadCpuMs"]["value"], 160)
        self.assertEqual(totals["metrics"]["inferenceWorkerRunCount"]["value"], 3)
        self.assertEqual(totals["measurement_scopes"]["inferenceThreadCpuScope"], {"coordinator": 1})
        self.assertEqual(totals["stages"]["inference"]["measurement_scopes"]["wallScope"], {"critical-path": 1})
        graph = totals["graphs"]["block-00-time"]
        self.assertEqual(graph["runWallMs"]["value"], 240)
        self.assertIsNone(graph["runProcessCpuMs"]["value"])
        self.assertEqual(graph["measurement_scopes"]["graphWallScope"], {"aggregate-call": 1})
        self.assertEqual(graph["measurement_scopes"]["runProcessCpuScope"], {"unavailable-overlapping-intervals": 1})
        private = report(*events).replace("inferenceThreadCpuScope=coordinator", "inferenceThreadCpuScope=PRIVATE_SCOPE")
        private = private.replace("graphWallScope=aggregate-call", "graphWallScope=PRIVATE_SCOPE")
        sanitized = EVIDENCE.summarize(private)
        self.assertNotIn("PRIVATE_SCOPE", json.dumps(sanitized))
        unknown = sanitized["attempts"][0]["native_profiles"]["completed_complete_bundles"]
        self.assertEqual(unknown["measurement_scopes"]["inferenceThreadCpuScope"], {"missing-or-unknown": 1})

    def test_parallel_scheduler_configurations_are_strictly_family_specific(self):
        for workers in (4, 8):
            raw = f"cpu-i1-j1-d0-sequential-w{workers}-b1"
            self.assertEqual(EVIDENCE._scheduler_configuration(raw, temporal=True), raw)
            self.assertIsNone(EVIDENCE._scheduler_configuration(raw, temporal=False))
            frequency = f"cpu-i1-j1-d0-sequential-w{workers}-b16"
            self.assertEqual(EVIDENCE._scheduler_configuration(frequency, temporal=False), frequency)
            self.assertIsNone(EVIDENCE._scheduler_configuration(frequency, temporal=True))
        for invalid in ("cpu-i1-j1-d0-sequential-w4-b1", "cpu-i1-j1-d0-sequential-w16-b16", "cpu-i2-j1-d0-sequential-w4-b16"):
            self.assertIsNone(EVIDENCE._scheduler_configuration(invalid, temporal=False))
        for invalid in ("cpu-i1-j1-d0-sequential-w16-b1", "cpu-i1-j1-d0-sequential-w8-b4",
                        "cpu-i2-j1-d0-sequential-w8-b1", "cpu-i1-j1-d4-sequential-w8-b1", "PRIVATE_CONFIGURATION"):
            self.assertIsNone(EVIDENCE._scheduler_configuration(invalid, temporal=True))
        self.assertEqual(EVIDENCE._scheduler_configuration("cpu-i6-j1-d4-sequential", temporal=False),
                         "cpu-i6-j1-d4-sequential")

    def test_pipeline_copy_scopes_preserve_overlap_and_do_not_reconstruct_totals(self):
        events = (
            event(0, "native-inference-profile",
                  "schema=native-inference-profile-v2 outcome=completed wallMs=140 inferenceWallMs=120 "
                  "instrumentedCpuMs=13 instrumentedCpuScope=nonoverlapping-calling-thread "
                  "inferenceThreadCpuMs=12 inferenceProcessCpuMs=174 inferenceCount=3 "
                  "inferenceWorkerThreadCpuMs=150 inferenceWorkerRunCount=2 inferenceWorkerCpuTelemetry=available "
                  "inferenceWallScope=critical-path inferenceThreadCpuScope=coordinator "
                  "inferenceWorkScope=run-and-pipeline-coordination "
                  "stageRecords=3 graphRecords=2 droppedStageRecords=0 droppedGraphRecords=0"),
            event(.001, "native-inference-profile",
                  "schema=native-inference-stage-v1 stage=inference samples=2 wallMs=120 cpuMs=12 processCpuMs=174 "
                  "wallScope=critical-path workScope=run-and-pipeline-coordination"),
            event(.002, "native-inference-profile",
                  "schema=native-inference-stage-v1 stage=pack samples=2 wallMs=9 cpuMs=4 processCpuMs=unavailable "
                  "wallScope=mixed-nested-and-sequential-intervals processCpuScope=unavailable-overlapping-intervals"),
            event(.003, "native-inference-profile",
                  "schema=native-inference-stage-v1 stage=scatter samples=1 wallMs=7 cpuMs=2 processCpuMs=unavailable "
                  "wallScope=nested-in-inference-pipeline processCpuScope=unavailable-overlapping-intervals"),
            event(.004, "native-inference-profile",
                  "schema=native-inference-graph-v2 graph=block-00-time runCount=2 runWallMs=180 runCpuMs=150 "
                  "runProcessCpuMs=unavailable graphWallScope=aggregate-call "
                  "packWallScope=nested-in-inference-pipeline scatterWallScope=nested-in-inference-pipeline "
                  "packProcessCpuScope=unavailable-overlapping-intervals scatterProcessCpuScope=unavailable-overlapping-intervals "
                  "packWallMs=5 packCpuMs=3 packProcessCpuMs=unavailable scatterWallMs=7 scatterCpuMs=2 scatterProcessCpuMs=unavailable"),
            event(.005, "native-inference-profile",
                  "schema=native-inference-graph-v2 graph=block-00-frequency runCount=1 runWallMs=20 runCpuMs=2 "
                  "packWallScope=sequential-intervals scatterWallScope=unavailable packWallMs=4 packCpuMs=1 packProcessCpuMs=2"),
        )
        totals = EVIDENCE.summarize(report(*events))["attempts"][0]["native_profiles"]["completed_complete_bundles"]
        self.assertEqual(totals["metrics"]["instrumentedCpuMs"]["value"], 13)
        self.assertEqual(totals["metrics"]["inferenceWallMs"]["value"], 120)
        self.assertEqual(totals["measurement_scopes"]["instrumentedCpuScope"], {"nonoverlapping-calling-thread": 1})
        self.assertEqual(totals["measurement_scopes"]["inferenceWorkScope"], {"run-and-pipeline-coordination": 1})
        self.assertEqual(totals["stages"]["pack"]["measurement_scopes"]["wallScope"], {"mixed-nested-and-sequential-intervals": 1})
        self.assertEqual(totals["stages"]["scatter"]["measurement_scopes"]["wallScope"], {"nested-in-inference-pipeline": 1})
        graph = totals["graphs"]["block-00-time"]
        self.assertEqual(graph["packCpuMs"]["value"], 3)
        self.assertIsNone(graph["packProcessCpuMs"]["value"])
        self.assertEqual(graph["measurement_scopes"]["packWallScope"], {"nested-in-inference-pipeline": 1})
        self.assertEqual(graph["measurement_scopes"]["scatterProcessCpuScope"], {"unavailable-overlapping-intervals": 1})
        private = report(*events).replace("nested-in-inference-pipeline", "PRIVATE_SCOPE")
        self.assertNotIn("PRIVATE_SCOPE", json.dumps(EVIDENCE.summarize(private)))

    def test_durable_summary_does_not_override_current_job_and_keeps_partial_cpu_honest(self):
        text = report().replace("jobRef=PRIVATE_JOB_IDENTIFIER", "jobRef=1234567890abcdef")
        text = text.replace("ANDROID PREVIOUS PROCESS EXITS", "\n".join((
            "DURABLE ANALYSIS SUMMARIES (independent of trace rotation)",
            "schema=diagnostic-job-summary-v1 retentionJobs=3 storageBoundBytes=32768 recovery=normal",
            "jobRef=1234567890abcdef state=completed lifecycleElapsedMs=12345 durationMs=177000 analysisQuality=precision recoveryGaps=0 completedStages=4 restoredStages=0 createdAt=PRIVATE_TIMESTAMP",
            " stage=save observedWallMs=345",
            " route=native-deux-v1 passages=2 completed=1 cancelled=1 otherOutcomes=0 inferenceWallMs=100 inferenceWallMsMeasuredPassages=2 inferenceProcessCpuMs=90 inferenceProcessCpuMsMeasuredPassages=1 inferenceThreadCpuMs=unavailable inferenceThreadCpuMsMeasuredPassages=0 lastTemporalConfig=cpu-i6-j1-d4-sequential lastFrequencyConfig=PRIVATE_CONFIGURATION PRIVATE_FIELD=PRIVATE_NAME",
            "jobRef=abcdef1234567890 state=failed lifecycleElapsedMs=99 durationMs=9000 analysisQuality=balanced restoredStages=999",
            " stage=PRIVATE_PATH observedWallMs=999",
            "ANDROID PREVIOUS PROCESS EXITS",
        )))
        result = EVIDENCE.summarize(text)
        self.assertEqual(result["current_job_snapshot"]["state"], "completed")
        self.assertEqual(result["current_job_snapshot"]["analysisQuality"], "precision")
        self.assertEqual(result["current_job_snapshot"]["restoredStages"]["value"], 2)
        jobs = result["durable_job_summaries"]
        self.assertEqual(len(jobs), 2)
        self.assertTrue(jobs[0]["matches_current_job"])
        self.assertFalse(jobs[1]["matches_current_job"])
        self.assertEqual(jobs[0]["stages"]["save"]["observed_wall_ms"]["value"], 345)
        config = jobs[0]["native_routes"]["native-deux-v1"]["last_scheduling_configuration"]
        self.assertEqual(config["lastTemporalConfig"], "cpu-i6-j1-d4-sequential")
        self.assertIsNone(config["lastFrequencyConfig"])
        metrics = jobs[0]["native_routes"]["native-deux-v1"]["metrics"]
        self.assertEqual(metrics["inferenceWallMs"]["value"], 100)
        self.assertEqual(metrics["inferenceProcessCpuMs"]["status"], "partial")
        self.assertIsNone(metrics["inferenceProcessCpuMs"]["value"])
        self.assertEqual(metrics["inferenceProcessCpuMs"]["observed_subtotal"], 90)
        self.assertEqual(metrics["inferenceThreadCpuMs"]["status"], "unavailable")
        self.assertIsNone(result["full_song_runtime_ms"]["value"])
        serialized = json.dumps(result)
        for excluded in ("1234567890abcdef", "abcdef1234567890", "PRIVATE_TIMESTAMP", "PRIVATE_NAME", "PRIVATE_PATH", "PRIVATE_CONFIGURATION"):
            self.assertNotIn(excluded, serialized)

    def test_rotated_start_is_partial_and_snapshot_is_not_full_runtime(self):
        result = EVIDENCE.summarize(report(
            event(0, "native-inference-profile", "schema=native-inference-graph-v2 graph=front runWallMs=999"),
            event(1, "analysis-worker", "stage=separation passageIndex=18 passageCount=35 restoredPassages=0"),
            event(1, "native-passage", "started; passage=PRIVATE_PASSAGE_ID"),
            event(2, "native-passage", "completed; passage=PRIVATE_PASSAGE_ID; elapsedMs=1000"),
            *profile(2), event(3, "analysis-worker", "Stage completed: separation"),
            event(4, "analysis-shutdown", "job=PRIVATE_JOB_IDENTIFIER; state=completed"),
        ))
        attempt = result["attempts"][0]
        self.assertEqual(attempt["kind"], "historical_partial")
        self.assertEqual(attempt["attempt_wall_ms"]["status"], "partial")
        self.assertEqual(attempt["attempt_wall_ms"]["observed_subtotal"], 4000)
        self.assertIsNone(attempt["stages"][0]["wall_ms"]["value"])
        self.assertEqual(attempt["native_profiles"]["completed_complete_bundles"]["metrics"]["wallMs"]["value"], 100)
        self.assertEqual(len(result["source"]["unassociated_profile_detail_lines"]), 1)
        self.assertEqual(result["current_job_snapshot"]["elapsedMs"]["value"], 12000)
        self.assertIsNone(result["full_song_runtime_ms"]["value"])
        self.assertEqual(attempt["passages"]["native_separation"]["completed_executed_ms"]["value"], 1000)

    def test_incomplete_and_noncompleted_profiles_never_join_complete_totals(self):
        result = EVIDENCE.summarize(report(
            *profile(0, wall="100"),
            *profile(1, wall="900", details=False),
            *profile(2, wall="700", outcome="cancelled"),
            *profile(3, wall="800", graph_count=2),
        ))
        profiles = result["attempts"][0]["native_profiles"]
        self.assertEqual(profiles["completed_complete_bundles"]["count"], 1)
        self.assertEqual(profiles["completed_complete_bundles"]["metrics"]["wallMs"]["value"], 100)
        self.assertEqual(profiles["incomplete_bundles"]["count"], 2)
        self.assertEqual(profiles["incomplete_bundles"]["metrics"]["wallMs"]["value"], 1700)
        self.assertEqual(profiles["other_outcomes_complete_bundles"]["metrics"]["wallMs"]["value"], 700)

    def test_complete_native_receipt_with_engine_initialization_is_retained(self):
        # Full producer topology, including optional addEngineInit(). Keep the
        # fixture independent of the parser vocabulary so omissions fail here.
        stages = (
            "inference-gate-wait", "engine-init", "cache-preflight", "buffer-init",
            "runtime-setup", "pcm-read", "feature-encode", "model-init", "tensor-bind",
            "inference", "pack", "scatter", "decode", "output-write", "output-flush", "output-commit",
        )
        graphs = ("front", "head-0", "head-1") + tuple(
            f"block-{index:02d}-{axis}" for index in range(12) for axis in ("time", "frequency")
        )
        events = [event(0, "native-inference-profile",
                        "schema=native-inference-profile-v2 outcome=completed wallMs=500 engineInitWallMs=7 "
                        "cpuTelemetry=available instrumentedCpuMs=470 stageRecords=16 graphRecords=27 "
                        "droppedStageRecords=0 droppedGraphRecords=0")]
        events.extend(event(.001, "native-inference-profile",
                            f"schema=native-inference-stage-v1 stage={stage} samples=1 "
                            f"wallMs={7 if stage == 'engine-init' else 1} cpuTelemetry=available cpuMs=1")
                      for stage in stages)
        events.extend(event(.002, "native-inference-profile",
                            f"schema=native-inference-graph-v2 graph={graph} runCount=1 runWallMs=1 runCpuMs=1")
                      for graph in graphs)
        profiles = EVIDENCE.summarize(report(*events))["attempts"][0]["native_profiles"]
        complete = profiles["completed_complete_bundles"]
        self.assertEqual(complete["count"], 1)
        self.assertEqual(profiles["incomplete_bundles"]["count"], 0)
        self.assertEqual(len(complete["stages"]), 16)
        self.assertEqual(len(complete["graphs"]), 27)
        self.assertEqual(complete["stages"]["engine-init"]["wallMs"]["value"], 7)
        self.assertEqual(complete["metrics"]["engineInitWallMs"]["value"], 7)
        self.assertEqual(complete["metrics"]["wallMs"]["value"], 500)

    def test_partial_cpu_telemetry_is_preserved_without_inventing_total_cpu_time(self):
        result = EVIDENCE.summarize(report(
            *profile(0, cpu_telemetry="available", instrumented_cpu="80"),
            *profile(1, cpu_telemetry="partial", instrumented_cpu="unavailable"),
        ))
        complete = result["attempts"][0]["native_profiles"]["completed_complete_bundles"]
        self.assertEqual(complete["count"], 2)
        self.assertEqual(complete["telemetry"]["cpuTelemetry"], {"available": 1, "partial": 1})
        self.assertEqual(complete["metrics"]["wallMs"]["value"], 200)
        cpu = complete["metrics"]["instrumentedCpuMs"]
        self.assertEqual(cpu["status"], "partial")
        self.assertIsNone(cpu["value"])
        self.assertEqual(cpu["observed_subtotal"], 80)
        self.assertEqual(cpu["unavailable_count"], 1)

    def test_missing_unavailable_invalid_and_zero_remain_distinct(self):
        result = EVIDENCE.summarize(report(*profile(0), *profile(1, inference="unavailable")))
        metrics = result["attempts"][0]["native_profiles"]["completed_complete_bundles"]["metrics"]
        self.assertEqual(metrics["waitWallMs"]["status"], "observed")
        self.assertEqual(metrics["waitWallMs"]["value"], 0)
        self.assertEqual(metrics["inferenceWallMs"]["status"], "partial")
        self.assertIsNone(metrics["inferenceWallMs"]["value"])
        self.assertEqual(metrics["inferenceWallMs"]["observed_subtotal"], 90)
        self.assertEqual(metrics["inferenceWallMs"]["unavailable_count"], 1)
        self.assertEqual(metrics["instrumentedCpuMs"]["unavailable_count"], 2)
        self.assertEqual(metrics["preprocessWallMs"]["missing_count"], 2)
        for raw in ("NaN", "Infinity", "-1", "private-value"):
            self.assertEqual(EVIDENCE.number(raw)["reason"], "invalid")
        overflow = EVIDENCE.aggregate([{"x": "1e308"}] * 3, "x")
        self.assertTrue(overflow["overflowed"])
        self.assertIsNone(overflow["value"])

    def test_interrupted_work_idle_gap_and_resumed_passages_are_separate(self):
        result = EVIDENCE.summarize(report(
            event(0, "background", "Analysis state=queued"),
            event(.1, "analysis-service", "starting job=PRIVATE_JOB_IDENTIFIER"),
            event(.2, "background", "Runner started"),
            event(1, "analysis-worker", "Stage started: voice"),
            event(1, "analysis-worker", "stage=voice passageIndex=1 passageCount=2 restoredPassages=0 restoredStages=0"),
            event(3, "analysis-progress", "stage=GAME Large; checkpoint=true; passage=1; completed=1"),
            event(3, "analysis-worker", "stage=voice passageIndex=2 passageCount=2 restoredPassages=0"),
            event(5, "analysis-renderer", "Android reclaimed renderer PRIVATE_STACK_TRACE", "ERROR"),
            event(5, "analysis-finish", "job=PRIVATE_JOB_IDENTIFIER; state=interrupted", "WARN"),
            event(5.1, "analysis-shutdown", "state=interrupted"),
            event(20, "background", "Analysis state=queued"),
            event(21, "analysis-worker", "Stage started: rhythm"),
            event(21.1, "analysis-progress", "stage=Completed rhythm work restored; checkpoint=true"),
            event(21.2, "analysis-worker", "Stage completed: rhythm"),
            event(22, "analysis-worker", "Stage started: voice"),
            event(22, "analysis-worker", "stage=voice passageIndex=1 passageCount=2 restoredPassages=0"),
            event(22.1, "analysis-progress", "stage=GAME Large; checkpoint=true; passage=1; completed=1"),
            event(22.1, "progress", "stage=working passageIndex=1 restoredPassages=1"),
            event(22.2, "analysis-worker", "stage=voice passageIndex=2 passageCount=2 restoredPassages=1"),
            event(24, "analysis-progress", "stage=GAME Large; checkpoint=true; passage=2; completed=2"),
            event(24.1, "analysis-worker", "Stage completed: voice"),
            event(25, "analysis-shutdown", "state=completed"),
            event(50, "activity", "resumed"),
        ))
        first, resumed = result["attempts"]
        self.assertEqual(first["kind"], "fresh")
        self.assertEqual(first["cold_cache_status"], "not-established")
        self.assertEqual(first["attempt_wall_ms"]["value"], 5000)
        self.assertEqual(first["passages"]["voice"]["records"][1]["wall_ms"]["status"], "partial")
        self.assertEqual(first["passages"]["voice"]["records"][1]["wall_ms"]["observed_subtotal"], 2000)
        self.assertEqual(result["interruption_gaps"][0]["until_next_attempt_ms"]["value"], 15000)
        self.assertEqual(resumed["kind"], "resumed")
        self.assertEqual(resumed["attempt_wall_ms"]["value"], 5000)
        self.assertEqual(resumed["stages"][0]["work"], "restored")
        self.assertEqual(resumed["stages"][0]["wall_ms"]["value"], 200)
        self.assertEqual(resumed["passages"]["voice"]["completed_restored_ms"]["value"], 100)
        self.assertEqual(resumed["passages"]["voice"]["completed_executed_ms"]["value"], 1800)
        self.assertEqual(resumed["restored_voice_passages"]["value"], 1)
        self.assertEqual(len(result["renderer_events"]), 1)

    def test_snapshot_completion_cannot_complete_unfinished_trace(self):
        result = EVIDENCE.summarize(report(
            event(0, "background", "Analysis state=queued"),
            event(1, "analysis-worker", "Stage started: rhythm"),
            event(2, "analysis-worker", "stage=rhythm progress=10%"),
        ))
        attempt = result["attempts"][0]
        self.assertEqual(attempt["terminal"], "not-observed")
        self.assertEqual(attempt["attempt_wall_ms"]["status"], "partial")
        self.assertIsNone(attempt["stages"][0]["wall_ms"]["value"])

    def test_separation_restore_does_not_become_voice_restore_from_ui_label(self):
        result = EVIDENCE.summarize(report(
            event(0, "background", "Analysis state=queued"),
            event(1, "analysis-worker", "stage=separation passageIndex=3 passageCount=5 restoredPassages=2 restoredStages=0"),
            event(1.1, "background", "stage=voice passageIndex=3 passageCount=5 restoredPassages=2"),
            event(2, "analysis-shutdown", "state=interrupted"),
        ))
        attempt = result["attempts"][0]
        self.assertEqual(attempt["kind"], "resumed")
        self.assertIsNone(attempt["restored_voice_passages"]["value"])
        self.assertIsNone(result["interruption_gaps"][0]["until_next_attempt_ms"]["value"])

    def test_new_queued_attempt_does_not_merge_unfinished_previous_attempt(self):
        result = EVIDENCE.summarize(report(
            event(0, "background", "Analysis state=queued"),
            event(1, "analysis-worker", "Stage started: rhythm"),
            event(10, "background", "Analysis state=queued"),
            event(11, "analysis-worker", "Stage started: voice"),
        ))
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(result["attempts"][0]["end_offset_ms"], 1000)
        self.assertEqual(result["attempts"][1]["start_offset_ms"], 10000)

    def test_out_of_order_clock_cannot_produce_negative_runtime(self):
        result = EVIDENCE.summarize(report(
            event(2, "background", "Analysis state=queued"),
            event(1, "analysis-shutdown", "state=completed"),
        ))
        self.assertEqual(result["attempts"][0]["attempt_wall_ms"]["reason"], "clock-moved-backwards")

    def test_preview_pair_uses_nonce_internally_without_disclosing_it(self):
        result = EVIDENCE.summarize(report(
            event(0, "completed-restore-watchdog", "completed-restore lease begin job=PRIVATE_JOB_IDENTIFIER nonce=PRIVATE_PREVIEW_ID"),
            event(1.25, "completed-restore-watchdog", "visual hardware frame committed job=PRIVATE_JOB_IDENTIFIER nonce=PRIVATE_PREVIEW_ID"),
            event(2, "completed-restore-watchdog", "visual hardware frame committed nonce=UNMATCHED_PRIVATE_ID"),
        ))
        self.assertEqual(result["attempts"], [])
        preview = result["completed_preview_restoration"]
        self.assertEqual(preview[0]["hardware_frame_ms"]["value"], 1250)
        self.assertIsNone(preview[1]["hardware_frame_ms"]["value"])
        encoded = json.dumps(result)
        for private in ("PRIVATE", "2000-01-01", "jobRef", "nonce", "description"):
            self.assertNotIn(private, encoded)

    def test_unknown_profile_labels_and_malformed_events_do_not_leak_content(self):
        lines = profile(0, graph_count=2)
        lines.append(event(.003, "native-inference-profile", "schema=native-inference-graph-v2 graph=PRIVATE_GRAPH_NAME runWallMs=123"))
        lines.append("PRIVATE_UNPARSEABLE_LINE")
        result = EVIDENCE.summarize(report(*lines))
        self.assertEqual(result["attempts"][0]["native_profiles"]["incomplete_bundles"]["count"], 1)
        self.assertEqual(len(result["source"]["malformed_event_lines"]), 1)
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_cli_refuses_to_overwrite_input_or_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "input.txt"
            output = Path(temporary) / "output.json"
            source.write_text(report(*profile(0)))
            command = [sys.executable, str(ROOT / "tools/diagnostic_evidence.py"), "--report", str(source), "--output", str(output)]
            subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(output.read_text())["schema"], "lightforge.diagnostic-evidence.v1")
            existing = output.read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(output.read_bytes(), existing)
            command[-1] = str(source)
            original = source.read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(source.read_bytes(), original)

    def test_bad_or_absent_trace_is_rejected(self):
        with self.assertRaises(ValueError):
            EVIDENCE.summarize("not a report")
        with self.assertRaises(ValueError):
            EVIDENCE.summarize("LIGHTFORGE DIAGNOSTIC REPORT\n")


if __name__ == "__main__":
    unittest.main()
