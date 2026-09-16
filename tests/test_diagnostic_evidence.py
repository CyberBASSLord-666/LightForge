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


def profile(seconds, *, wall="100", inference="90", outcome="completed", graph_count=1, details=True):
    lines = [event(seconds, "native-inference-profile",
                   f"schema=native-inference-profile-v2 outcome={outcome} wallMs={wall} inferenceWallMs={inference} "
                   "waitWallMs=0 instrumentedCpuMs=unavailable cpuTelemetry=unavailable "
                   f"acceleratorTelemetry=unavailable stageRecords=1 graphRecords={graph_count} "
                   "droppedStageRecords=0 droppedGraphRecords=0 cacheModelHits=1 cacheModelMisses=0 "
                   "PRIVATE_FIELD=PRIVATE_PROFILE_TEXT")]
    if details:
        lines += [event(seconds + .001, "native-inference-profile",
                        "schema=native-inference-stage-v1 stage=inference samples=1 wallMs=90 cpuMs=unavailable"),
                  event(seconds + .002, "native-inference-profile",
                        "schema=native-inference-graph-v2 graph=front runCount=1 runWallMs=90 runCpuMs=unavailable")]
    return lines


class DiagnosticEvidenceTest(unittest.TestCase):
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
