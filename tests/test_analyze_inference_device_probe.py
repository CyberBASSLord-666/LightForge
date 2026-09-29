"""Offline receipt integrity checks; synthetic observations, no device or inference."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("device_probe_analysis", ROOT / "tools/analyze_inference_device_probe.py")
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)
SOURCE, SOURCE_SHA = PROBE.load(ROOT / (PROBE.REFERENCE + "device-probe-sources.json"))
BUILD, _ = PROBE.load(ROOT / (PROBE.REFERENCE + "device-probe-build.json"))
IDENTITY = {"declared_model_bytes": 921547393, "qualification_ordinals": [0, 4, 8]}


def output_hash(start):
    return hashlib.sha256(str(start).encode()).hexdigest()


def policies(index, paired=False):
    ordinals = [ordinal for ordinal in (0, 4, 8) if paired and ordinal <= index]
    count = len(ordinals)
    header = (f"schema=native-passage-policy-v1 state={'qualified' if count == 3 else 'provisional' if count else 'baseline'} "
              f"workers={4 if count else 0} reason={'measured-passage-improvement' if count else 'memory-ineligible'} "
              f"extraNanos={150000000*count} extraCapNanos=360000000000 projectedAccruedSavingsNanos=0 "
              f"qualificationPairs={count} currentJobPairs={count} seeded=false activePassages=0 leasePassages=8 paybackScope=projected-not-measured")
    rows = [header]
    for number, ordinal in enumerate(ordinals):
        rows.append(f"schema=native-passage-pair-v1 role=qualification index={number} ordinal={ordinal} "
                    f"candidateFirst={str(number % 2 == 1).lower()} workers=4 baselineNanos=200000000 candidateNanos=150000000 "
                    f"extraNanos=150000000 outputSha256={output_hash(PROBE.STARTS[ordinal % 5])} "
                    "finite=true exact=true fullGeometry=true coldSessions=true")
    return rows


def alternate_policies(index):
    count = min(index, 3)
    header = (f"schema=native-passage-policy-v1 state={'qualified' if count == 3 else 'provisional'} "
              f"workers=4 reason={'measured-passage-improvement' if count == 3 else 'alternate-pending' if count == 0 else 'qualification-pending'} "
              f"extraNanos={225000000 + 150000000 * count} extraCapNanos=360000000000 "
              "projectedAccruedSavingsNanos=0 "
              f"qualificationPairs={count} currentJobPairs={count + 1} seeded=false activePassages=0 "
              "leasePassages=8 paybackScope=projected-not-measured")
    records = [header, "schema=native-passage-pair-v1 role=rejected index=0 ordinal=0 candidateFirst=false "
               "workers=8 baselineNanos=200000000 candidateNanos=220000000 extraNanos=220000000 "
               f"outputSha256={output_hash(PROBE.STARTS[0])} finite=true exact=true fullGeometry=true coldSessions=true"]
    for number in range(count):
        ordinal = number + 1
        records.append(f"schema=native-passage-pair-v1 role=qualification index={number} ordinal={ordinal} "
                       f"candidateFirst={str(number == 1).lower()} workers=4 baselineNanos=200000000 "
                       f"candidateNanos=150000000 extraNanos=150000000 outputSha256={output_hash(PROBE.STARTS[ordinal % 5])} "
                       "finite=true exact=true fullGeometry=true coldSessions=true")
    return records


def alternate_receipt():
    document = receipt()
    for index, passage in enumerate(document["passages"]):
        records = alternate_policies(index)
        rows = profile(index)
        rows[0] = rows[0].split(" passagePolicy=")[0] + " passagePolicy=" + "|".join(row.replace(" ", ",") for row in records)
        passage["profile"] = rows[:29] + records
    return document


def profile(index, paired=False):
    policy = policies(index, paired)
    header = ("schema=native-inference-profile-v2 outcome=completed wallMs=1000 inferenceWallMs=900 inferenceCount=335 sessionInitCount=27 "
              "temporalConfig=cpu-i4-j1-d0-sequential temporalConfigCountScope=session-init-attempts "
              "temporalBaselineSessionCount=12 temporalFourWorkerSessionCount=0 temporalEightWorkerSessionCount=0 temporalUnobservedSessionCount=0 "
              "stageRecords=1 graphRecords=27 droppedStageRecords=0 droppedGraphRecords=0 passagePolicy=" + "|".join(row.replace(" ", ",") for row in policy))
    rows = [header, "schema=native-inference-stage-v1 stage=inference samples=335 wallMs=900"]
    for graph in sorted(PROBE.EVIDENCE.NATIVE_GRAPHS):
        count = 1 if graph == "front" else 15 if graph.endswith("-time") else 11
        rows.append(f"schema=native-inference-graph-v2 graph={graph} runCount={count} runWallMs=20")
    return rows + policy


def receipt(paired=False):
    rows = []
    for index in range(35):
        rows.append({"ordinal": index, "remainingUseful": 35-index, "startSample": PROBE.STARTS[index % 5], "outcome": "completed",
                     "predictWallNanos": 1000000000, "predictProcessCpuMillis": 3000,
                     "before": {"elapsedRealtimeMillis": 1+index*1000, "thermalStatus": 0},
                     "after": {"elapsedRealtimeMillis": 1001+index*1000, "thermalStatus": 0},
                     "output": {"bytes": 4586400, "floatCount": 1146600, "finite": True, "maxAbs": .25, "sha256": output_hash(PROBE.STARTS[index % 5])},
                     "profile": profile(index, paired)})
    return {"schema": "lightforge.inference-device-probe.v1", "source": copy.deepcopy(SOURCE), "plannedPassages": 35,
            "completedPassages": 35, "freshPolicyCache": True, "terminal": True, "outcome": "completed", "cancelReason": "",
            "inferenceCoordinatorFinished": True, "engineCloseReturned": True, "nativeResourceCleanupConfirmed": True, "temporaryCacheRemoved": True,
            "installedAssetPackage": {**SOURCE["expectedInstalledPackage"], "versionName": "2.4.1"},
            "modelManifestSha256": SOURCE["modelManifestSha256"], "declaredModelBytes": 921547393,
            "elapsedMillis": 35002, "processCpuMillis": 105000, "before": {"elapsedRealtimeMillis": 0}, "after": {"elapsedRealtimeMillis": 35002}, "passages": rows}


def configured_profile(index, temporal=12, frequency=12, workers=4, *, paired=False, legacy_frequency=False):
    rows = profile(index, paired)
    calls = 335 + 45*temporal + 71*frequency
    family = f"cpu-i1-j1-d0-sequential-w{workers}-b"
    rows[0] = rows[0].replace("inferenceCount=335", f"inferenceCount={calls}")
    rows[0] = rows[0].replace("temporalBaselineSessionCount=12", f"temporalBaselineSessionCount={12-temporal}")
    key = "temporalFourWorkerSessionCount" if workers == 4 else "temporalEightWorkerSessionCount"
    rows[0] = rows[0].replace(key+"=0", key+"="+str(temporal))
    if temporal == 12:
        rows[0] = rows[0].replace("temporalConfig=cpu-i4-j1-d0-sequential", "temporalConfig="+family+"1")
    if not legacy_frequency:
        rows[0] += (" frequencyConfigCountScope=session-init-attempts"
                    f" frequencyBaselineSessionCount={12-frequency} frequencyFourWorkerSessionCount={frequency if workers == 4 else 0}"
                    f" frequencyEightWorkerSessionCount={frequency if workers == 8 else 0} frequencyUnobservedSessionCount=0"
                    " frequencyConfig=" + (family+"16" if frequency == 12 else "cpu-i4-j1-d0-sequential"))
    rows[1] = rows[1].replace("samples=335", f"samples={calls}")
    for index, row in enumerate(rows):
        fields = dict(PROBE.EVIDENCE.FIELD.findall(row))
        graph = fields.get("graph", "")
        if graph.startswith("block-"):
            number = int(graph.split("-")[1])
            if graph.endswith("-time") and number < temporal:
                rows[index] = row.replace("runCount=15", "runCount=60")
            if graph.endswith("-frequency") and number < frequency:
                rows[index] = row.replace("runCount=11", "runCount=82")
        if graph:
            calls = int(dict(PROBE.EVIDENCE.FIELD.findall(rows[index]))["runCount"])
            bindings = workers if graph.endswith("-time") and calls == 60 else workers + 1 if graph.endswith("-frequency") and calls == 82 else calls
            rows[index] += f" sessionInitCount=1 tensorBindCount={bindings}"
    return rows


def candidate(index, *, frequency=12, paired=False):
    rows = configured_profile(index, frequency=frequency, paired=paired)[:29]
    # Remove only the encoded policy token: all explicit family fields remain.
    rows[0] = " ".join(token for token in rows[0].split(" ") if not token.startswith("passagePolicy="))
    setup = {"verifiedModelsBefore": 27, "verifiedModelsAfter": 27, "extractionAttempts": 0, "extractionBytesRead": 0,
             "existingFileChecksumAttempts": 0, "existingFileChecksumBytesRead": 0}
    return {"schema": "native-passage-candidate-evidence-v1", "ordinal": index, "workers": 4, "candidateFirst": index == 4,
            "commonPreflightVerifiedModelCount": 27, **PROBE.AUXILIARY_SCOPES,
            "baseline": {"outcome": "completed", "armWallNanos": 200000000, "modelSetup": copy.deepcopy(setup)},
            "candidate": {"outcome": "completed", "armWallNanos": 150000000, "modelSetup": copy.deepcopy(setup)}, "profile": rows}


class DeviceProbeAnalysisTest(unittest.TestCase):
    def test_frozen_schedule_reader_recognizes_only_bound_alternate_shift(self):
        source = (ROOT / "android/src/com/cyberbasslord/lightforge/NativePassagePolicy.java").read_text()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "NativePassagePolicy.java"
            path.write_text(source)
            self.assertEqual(PROBE.bound_qualification_schedules(path), ([0, 1, 2], [1, 2, 3]))
            path.write_text(source.replace("qualificationOrigin=1;", "qualificationOrigin=2;"))
            with self.assertRaises(ValueError):
                PROBE.bound_qualification_schedules(path)
            path.write_text("int due=qualificationCount; if(pair.ordinal!=qualificationCount||){}")
            self.assertEqual(PROBE.bound_qualification_schedules(path), ([0, 1, 2], None))
            path.write_text("int due=qualificationCount*4; if(pair.ordinal!=qualificationCount*4||){}")
            self.assertEqual(PROBE.bound_qualification_schedules(path), ([0, 4, 8], None))

    def test_rejected_eight_worker_pair_does_not_count_toward_alternate_qualification(self):
        identity = {**IDENTITY, "qualification_ordinals": [0, 1, 2], "alternate_qualification_ordinals": [1, 2, 3]}
        document = alternate_receipt()
        result = PROBE.analyze(document, SOURCE, identity)
        self.assertTrue(result["integrity"]["passed"], result["integrity"])
        self.assertEqual(len(result["unique_observed_pairs"]), 4)
        self.assertEqual(result["unique_observed_pairs"][0]["record"]["role"], "rejected")
        self.assertEqual(result["unique_observed_pairs"][0]["observed_arm_wall_reduction_percent"], -10)
        self.assertEqual(result["policy_overhead"]["unique_recorded_pair_extra_nanos"], 670000000)
        self.assertFalse(PROBE.analyze(document, SOURCE, {**identity, "alternate_qualification_ordinals": None})["integrity"]["passed"])
        self.assertFalse(PROBE.analyze(document, SOURCE, IDENTITY)["integrity"]["passed"])
        for ordinal, old, new in ((0, "role=rejected", "role=qualification"),
                                  (0, "workers=8", "workers=4"),
                                  (0, "candidateNanos=220000000", "candidateNanos=150000000"),
                                  (1, "ordinal=1", "ordinal=0"),
                                  (2, "candidateFirst=true", "candidateFirst=false")):
            forged = copy.deepcopy(document)
            for passage in forged["passages"][ordinal:]:
                passage["profile"] = [row.replace(old, new) for row in passage["profile"]]
            self.assertFalse(PROBE.analyze(forged, SOURCE, identity)["integrity"]["passed"], (ordinal, old, new))
        incomplete = copy.deepcopy(document)
        for passage in incomplete["passages"][3:]:
            records = alternate_policies(2)
            records[0] = records[0].replace("state=provisional", "state=qualified")
            rows = profile(3)
            rows[0] = rows[0].split(" passagePolicy=")[0] + " passagePolicy=" + "|".join(row.replace(" ", ",") for row in records)
            passage["profile"] = rows[:29] + records
        self.assertFalse(PROBE.analyze(incomplete, SOURCE, identity)["integrity"]["passed"])

    @unittest.skipUnless((ROOT / "build/inference-device-probe/run-w6e3elh2").is_dir(), "Retained diagnostic build is not present")
    def test_reviewed_source_closure_matches_repository_without_building(self):
        result = PROBE.verify_reference(SOURCE, BUILD, SOURCE_SHA, ROOT)
        self.assertEqual(result["historical_source_files_verified"], 15)
        self.assertEqual(result["declared_model_bytes"], 921547393)
        for mutate in (lambda source, build: source["sourceHashes"].update({"../outside.java": "a"*64}),
                       lambda source, build: build.update(sourceReceiptSha256="b"*64),
                       lambda source, build: source["fixture"].update(pcm16Sha256="c"*64)):
            source, build = copy.deepcopy(SOURCE), copy.deepcopy(BUILD)
            mutate(source, build)
            with self.assertRaises(ValueError):
                PROBE.verify_reference(source, build, SOURCE_SHA, ROOT)

    def test_complete_baseline_is_valid_observation_not_speedup(self):
        result = PROBE.analyze(receipt(), SOURCE, IDENTITY)
        self.assertTrue(result["integrity"]["passed"], result["integrity"])
        self.assertTrue(result["run"]["complete_35_passage_run"])
        self.assertEqual(result["whole_job_speedup"]["status"], "unavailable")
        self.assertEqual(result["host_output_comparison"]["status"], "not-comparable")
        self.assertEqual(result["qualification_status"], "not-evaluated")
        self.assertEqual(len(result["same_input_output_groups"]), 5)
        self.assertTrue(all(len(group["passage_ordinals"]) == 7 for group in result["same_input_output_groups"]))
        self.assertEqual(result["boundary_observations"][0]["thermalStatus"], None)

    def test_pairs_are_bound_to_outputs_and_deduplicated_not_added_as_work(self):
        result = PROBE.analyze(receipt(paired=True), SOURCE, IDENTITY)
        self.assertTrue(result["integrity"]["passed"], result["integrity"])
        self.assertEqual(len(result["unique_observed_pairs"]), 3)
        self.assertEqual(result["predict_wall_nanos"]["observed_sum"], 35000000000)
        self.assertEqual(result["policy_overhead"]["latest_cumulative_extra_nanos"], 450000000)
        self.assertTrue(all(pair["observed_arm_wall_reduction_percent"] == 25 for pair in result["unique_observed_pairs"]))

    def test_tampered_identity_geometry_outputs_cleanup_or_budget_cannot_pass(self):
        mutations = (
            lambda report: report["source"].update(runtimeVersion="other"),
            lambda report: report.update(modelManifestSha256="a"*64),
            lambda report: report["passages"][2].update(remainingUseful=35),
            lambda report: report["passages"][2].update(startSample=[0]),
            lambda report: report["passages"][1].update(ordinal=True),
            lambda report: report["passages"][1].update(startSample=False),
            lambda report: report["passages"][2].update(remainingUseful=33.0),
            lambda report: report["passages"][2]["output"].update(bytes=4),
            lambda report: report["passages"][5]["output"].update(sha256="f"*64),
            lambda report: report.update(temporaryCacheRemoved=False),
            lambda report: report.update(elapsedMillis=10),
            lambda report: report["passages"][4].update(profile=[]),
            lambda report: report["passages"][4].update(output=None),
        )
        for mutate in mutations:
            document = receipt(); mutate(document)
            result = PROBE.analyze(document, SOURCE, IDENTITY)
            self.assertFalse(result["integrity"]["passed"], mutate)
            self.assertFalse(result["run"]["complete_35_passage_run"])

    def test_rotated_or_cancelled_partial_run_is_never_complete(self):
        document = receipt()
        document.update(outcome="cancelled", completedPassages=3, passages=document["passages"][:3], cancelReason="user")
        result = PROBE.analyze(document, SOURCE, IDENTITY)
        self.assertTrue(result["integrity"]["passed"])
        self.assertFalse(result["run"]["complete_35_passage_run"])
        self.assertEqual(result["run"]["completed_passages"], 3)
        document["outcome"] = "completed"
        self.assertFalse(PROBE.analyze(document, SOURCE, IDENTITY)["integrity"]["passed"])

    def test_policy_record_conflict_bad_qualification_and_thermal_boundary(self):
        document = receipt(paired=True)
        document["passages"][10]["profile"] = [row.replace("candidateNanos=150000000", "candidateNanos=190000000")
                                                   for row in document["passages"][10]["profile"]]
        document["passages"][10]["before"]["thermalStatus"] = 3
        result = PROBE.analyze(document, SOURCE, IDENTITY)
        self.assertFalse(result["integrity"]["passed"])
        self.assertTrue(any("conflicting-repeated-pair" in error for error in result["integrity"]["errors"]))
        self.assertTrue(any("qualified-state-misses-median" in error for error in result["integrity"]["errors"]))
        self.assertTrue(any("severe" in warning for warning in result["integrity"]["warnings"]))

    def test_new_consecutive_pairs_and_unmatched_control_are_distinct(self):
        document = receipt()
        control = ("schema=native-passage-control-v1 ordinal=11 baselineNanos=200000000 previousBaselineNanos=200000000 "
                   "candidateMaxNanos=150000000 candidateSamples=3 accepted=true comparisonScope=unmatched-inputs")
        for index, passage in enumerate(document["passages"]):
            records = policies(min(index, 2)*4, paired=True)
            for number in (1, 2):
                records = [row.replace(f"ordinal={number*4} ", f"ordinal={number} ")
                           .replace(output_hash(PROBE.STARTS[number*4 % 5]), output_hash(PROBE.STARTS[number]))
                           for row in records]
            if index >= 11:
                records.append(control)
            # Keep the production profile intact; replace both forms of the policy snapshot.
            rows = profile(index)
            rows[0] = rows[0].split(" passagePolicy=")[0] + " passagePolicy=" + "|".join(row.replace(" ", ",") for row in records)
            passage["profile"] = rows[:29] + records
        identity = {**IDENTITY, "qualification_ordinals": [0, 1, 2]}
        result = PROBE.analyze(document, SOURCE, identity)
        self.assertTrue(result["integrity"]["passed"], result["integrity"])
        self.assertEqual(len(result["unique_observed_pairs"]), 3)
        self.assertEqual(len(result["unique_observed_controls"]), 1)
        self.assertEqual(result["policy_overhead"]["unique_recorded_pair_extra_nanos"], 450000000)
        control_result = result["unique_observed_controls"][0]
        self.assertIn("unmatched", control_result["comparison_scope"])
        self.assertEqual(control_result["extra_probe_nanos"], 0)
        self.assertIsNone(control_result["foregone_acceleration_nanos"])
        self.assertFalse(PROBE.analyze(document, SOURCE, IDENTITY)["integrity"]["passed"])
        for index in range(11, 35):
            document["passages"][index]["profile"] = [row.replace("candidateMaxNanos=150000000", "candidateMaxNanos=199000000")
                                                        for row in document["passages"][index]["profile"]]
        self.assertTrue(any("control-decision-mismatch" in error for error in
                            PROBE.analyze(document, SOURCE, identity)["integrity"]["errors"]))

    def test_json_loader_rejects_duplicates_nonfinite_and_oversize(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"receipt.json"
            for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', ' '*(PROBE.LIMIT+1)):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    PROBE.load(path)

    def test_new_frequency_geometry_mixed_fallback_and_legacy_temporal_only(self):
        for temporal, frequency, legacy in ((0, 0, False), (12, 0, True), (12, 12, False), (7, 6, False)):
            document = receipt()
            document["passages"][0]["profile"] = configured_profile(0, temporal, frequency, legacy_frequency=legacy)
            result = PROBE.analyze(document, SOURCE, IDENTITY)
            self.assertTrue(result["integrity"]["passed"], result["integrity"])
            counts = result["passages"][0]["frequency_session_attempt_counts"]
            self.assertEqual(counts["frequencyFourWorkerSessionCount"], None if legacy else frequency)
        for mutate in (
            lambda rows: rows.__setitem__(0, rows[0].replace("frequencyFourWorkerSessionCount=12", "frequencyFourWorkerSessionCount=11")),
            lambda rows: rows.__setitem__(0, rows[0].replace("frequencyBaselineSessionCount=0", "frequencyBaselineSessionCount=1")),
            lambda rows: rows.__setitem__(0, rows[0].replace("frequencyUnobservedSessionCount=0", "frequencyUnobservedSessionCount=1")),
            lambda rows: rows.__setitem__(0, rows[0].replace("frequencyConfigCountScope=session-init-attempts", "frequencyConfigCountScope=successful-runs")),
            lambda rows: rows.__setitem__(0, rows[0].replace("frequencyConfig=cpu-i1-j1-d0-sequential-w4-b16", "frequencyConfig=cpu-i1-j1-d0-sequential-w4-b1")),
            lambda rows: rows.__setitem__(0, rows[0].replace("inferenceCount=1727", "inferenceCount=875")),
            lambda rows: rows.__setitem__(2, rows[2].replace("runCount=82", "runCount=11")),
            lambda rows: rows.__setitem__(2, rows[2].replace("tensorBindCount=5", "tensorBindCount=9")),
            lambda rows: rows.__setitem__(2, rows[2].replace("sessionInitCount=1", "sessionInitCount=2")),
        ):
            document = receipt();document["passages"][0]["profile"] = configured_profile(0)
            mutate(document["passages"][0]["profile"])
            self.assertFalse(PROBE.analyze(document, SOURCE, IDENTITY)["integrity"]["passed"], mutate)
        document = receipt();document["passages"][0]["profile"] = configured_profile(0, legacy_frequency=True)
        self.assertFalse(PROBE.analyze(document, SOURCE, IDENTITY)["integrity"]["passed"])

    def test_auxiliary_candidate_profile_is_clock_bound_but_never_added_to_work(self):
        document = receipt(paired=True)
        before = PROBE.analyze(document, SOURCE, IDENTITY)
        for ordinal in (0, 4, 8):
            document["passages"][ordinal]["candidateEvidence"] = candidate(ordinal, paired=True)
        result = PROBE.analyze(document, SOURCE, IDENTITY)
        self.assertTrue(result["integrity"]["passed"], result["integrity"])
        self.assertEqual(result["predict_wall_nanos"], before["predict_wall_nanos"])
        self.assertEqual(result["unique_observed_pairs"], before["unique_observed_pairs"])
        self.assertEqual(result["policy_overhead"], before["policy_overhead"])
        self.assertEqual(result["whole_job_speedup"]["status"], "unavailable")
        auxiliary = result["passages"][0]["candidate_evidence"]
        self.assertEqual(auxiliary["paired_record_binding"], "matched-recorded-pair")
        self.assertEqual(auxiliary["candidate_profile"]["metrics"]["inferenceCount"]["value"], 1727)
        self.assertEqual(result["passages"][0]["production_inference_wall_millis"], 900)
        self.assertEqual(auxiliary["profile_wall_scope"], "collector-lifetime-not-arm-clock")
        self.assertTrue(auxiliary["preparation_fairness"]["matched_common_preflight_without_arm_file_preparation"])
        self.assertEqual(auxiliary["preparation_fairness"]["os_cache_equivalence"], "not-established")
        self.assertEqual(result["passages"][1]["candidate_evidence"]["status"], "unavailable")
        document["passages"][0]["candidateEvidence"]["baseline"]["modelSetup"].update(extractionAttempts=1, extractionBytesRead=500)
        result = PROBE.analyze(document, SOURCE, IDENTITY)
        self.assertTrue(result["integrity"]["passed"], result["integrity"])
        self.assertFalse(result["passages"][0]["candidate_evidence"]["preparation_fairness"]["matched_common_preflight_without_arm_file_preparation"])

    def test_partial_candidate_is_observation_without_pair_or_fake_arm_clock(self):
        document = receipt()
        raw = candidate(0);raw["candidateFirst"] = True;raw["baseline"] = None
        raw["candidate"].update(outcome="cancelled", armWallNanos=None)
        raw["profile"] = [raw["profile"][0].replace("outcome=completed", "outcome=cancelled")
                          .replace("graphRecords=27", "graphRecords=0").replace("stageRecords=1", "stageRecords=0")]
        document["passages"][0]["candidateEvidence"] = raw
        result = PROBE.analyze(document, SOURCE, IDENTITY)
        self.assertTrue(result["integrity"]["passed"], result["integrity"])
        auxiliary = result["passages"][0]["candidate_evidence"]
        self.assertEqual(auxiliary["status"], "observed")
        self.assertIsNone(auxiliary["arms"]["candidate"]["arm_wall_nanos"])
        self.assertEqual(auxiliary["paired_record_binding"], "unavailable")
        self.assertEqual(result["unique_observed_pairs"], [])
        self.assertFalse(auxiliary["preparation_fairness"]["matched_common_preflight_without_arm_file_preparation"])

    def test_malformed_or_misbound_auxiliary_evidence_fails_closed(self):
        mutations = (
            lambda raw: raw.update(ordinal=1), lambda raw: raw.update(workers=8), lambda raw: raw.update(candidateFirst=True),
            lambda raw: raw.update(commonPreflightVerifiedModelCount=True), lambda raw: raw.update(unreviewed="private"),
            lambda raw: raw.update(profileWallScope="arm-clock"), lambda raw: raw.update(comparisonScope="whole-job-speedup"),
            lambda raw: raw["candidate"].update(armWallNanos=150000001), lambda raw: raw["candidate"].update(armWallNanos=None),
            lambda raw: raw["baseline"].update(outcome="failed"), lambda raw: raw["candidate"]["modelSetup"].update(extractionAttempts=-1),
            lambda raw: raw["candidate"]["modelSetup"].update(verifiedModelsBefore=28),
            lambda raw: raw["candidate"]["modelSetup"].update(existingFileChecksumBytesRead=1.0),
            lambda raw: raw["profile"].append(policies(0)[0]), lambda raw: raw.update(profile=raw["profile"]*2),
        )
        for mutate in mutations:
            document = receipt(paired=True);raw = candidate(0);mutate(raw)
            document["passages"][0]["candidateEvidence"] = raw
            result = PROBE.analyze(document, SOURCE, IDENTITY)
            self.assertFalse(result["integrity"]["passed"], mutate)
            self.assertEqual(result["passages"][0]["candidate_evidence"]["status"], "invalid")
        document = receipt()
        for ordinal in range(4):
            document["passages"][ordinal]["candidateEvidence"] = candidate(ordinal)
        self.assertIn("too-many-candidate-evidence-records", PROBE.analyze(document, SOURCE, IDENTITY)["integrity"]["errors"])

    def test_historical_run01_still_validates_without_auxiliary_or_frequency_invention(self):
        raw, _ = PROBE.load(ROOT / (PROBE.REFERENCE + "device-probe-4a25e06032a3-run01.raw.json"))
        result = PROBE.analyze(raw, SOURCE, IDENTITY)
        self.assertTrue(result["integrity"]["passed"], result["integrity"])
        self.assertEqual(result["qualification_status"], "not-evaluated")
        for passage in result["passages"]:
            self.assertEqual(passage["candidate_evidence"]["status"], "unavailable")
            self.assertTrue(all(value is None for value in passage["frequency_session_attempt_counts"].values()))

    def test_current_source_gate_fails_without_invalidating_historical_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "receipt.json"
            input_path.write_text(json.dumps(receipt()))
            for required in (False, True):
                output_path = Path(directory) / (str(required) + ".json")
                argv = ["analyze", "--report", str(input_path), "--output", str(output_path)]
                if required:
                    argv.append("--require-current-source")
                identity = {**IDENTITY, "current_source_binding_passed": False, "historical_binding_passed": True}
                with mock.patch("sys.argv", argv), mock.patch.object(PROBE, "verify_reference", return_value=identity), mock.patch("builtins.print"):
                    self.assertEqual(PROBE.main(), 1 if required else 0)
                result = json.loads(output_path.read_text())
                self.assertTrue(result["integrity"]["passed"])
                self.assertFalse(result["current_source_gate"]["passed"])
                self.assertEqual(result["current_source_gate"]["required"], required)


if __name__ == "__main__":
    unittest.main()
