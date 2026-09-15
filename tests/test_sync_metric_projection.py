"""Cross-language producer/consumer checks; fixtures are not release evidence."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sync_projection", ROOT / "tools/project_sync_metrics.py")
projection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(projection)
PRODUCER = ROOT / "web/engine/perceptual-validation.js"


def produced(events):
    result = subprocess.run(["node", "-e", "const fs=require('node:fs'); const p=require(process.argv[1]); process.stdout.write(JSON.stringify(p.evaluate({}, {events:JSON.parse(fs.readFileSync(0,'utf8'))})));", str(PRODUCER)],
                            input=json.dumps(events), text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def project(report, basis="predicted"):
    raw = json.dumps(report).encode()
    return projection.project(report, perceptual_basis=basis, source_commit="1" * 40,
                              run_id="track-a-pair-01", report_sha256=hashlib.sha256(raw).hexdigest())


def event(name):
    return {"eventClass": name, "desiredPerceptualTime": 1, "commandTime": .97,
            "predictedPerceptualTime": 1.01, "measuredPerceptualTime": 1.02,
            "realizationStatus": "matched"}


class SyncProjectionTest(unittest.TestCase):
    def test_real_producer_preserves_three_different_timing_bases(self):
        report = produced([event(name) for name in projection.CLASSES])
        predicted, measured = project(report), project(report, "measured")
        self.assertEqual(len(predicted["metrics"]), 111)
        self.assertEqual(predicted["unobserved_metrics"], [])
        self.assertEqual(predicted["metrics"]["quality.sync.command.beat.p95_ms"], 30)
        self.assertEqual(predicted["metrics"]["quality.sync.perceptual.beat.p95_ms"], 10)
        self.assertEqual(measured["metrics"]["quality.sync.perceptual.beat.p95_ms"], 20)
        self.assertEqual(predicted["measurement_provenance"]["quality.sync.perceptual.beat.p95_ms"]["state"], "estimated")
        self.assertFalse(predicted["physical_validation_established"])
        self.assertFalse(predicted["release_qualified"])

    def test_class_aliases_are_explicit(self):
        result = project(produced([event("section-transition"), event("lighting-output"), event("movement")]))
        for name in ("section_transition", "lighting_output", "mechanical_actuator"):
            self.assertIn(f"quality.sync.command.{name}.max_ms", result["metrics"])
        self.assertNotIn("quality.sync.command.vocals.max_ms", result["metrics"])

    def test_missing_events_are_unobserved_not_zero_or_not_applicable(self):
        result = project(produced([]))
        self.assertEqual(result["metrics"], {})
        self.assertEqual(len(result["unobserved_metrics"]), 111)

    def test_prediction_never_substitutes_for_missing_measurement(self):
        row = event("beat"); row.pop("measuredPerceptualTime")
        result = project(produced([row]), "measured")
        self.assertIn("quality.sync.command.beat.p95_ms", result["metrics"])
        self.assertNotIn("quality.sync.perceptual.beat.p95_ms", result["metrics"])
        self.assertNotIn("quality.perceptual_sync_p95_ms", result["metrics"])

    def test_truncated_long_track_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            project(produced([event("beat")] * 10001))

    def test_invalid_event_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            project(produced([event("beat"), {"eventClass": "bass"}]))

    def test_omitted_classes_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            project(produced([event("custom-" + str(i)) for i in range(40)]))

    def test_non_monotonic_or_nonfinite_distribution_is_rejected(self):
        for value in (float("nan"), -1, 10001, 50):
            report = produced([event("beat")])
            report["perEventClass"]["beat"]["timing"]["predictedPerceptual"]["medianMs"] = value
            with self.assertRaises(ValueError):
                project(report)

    def test_mislabelled_prediction_is_rejected(self):
        report = produced([event("beat")])
        report["perEventClass"]["beat"]["timing"]["predictedPerceptual"]["state"] = "available"
        with self.assertRaisesRegex(ValueError, "state"):
            project(report)

    def test_inventory_and_aggregate_counts_must_agree(self):
        for change in ("accepted", "class", "aggregate"):
            report = produced([event("beat")])
            if change == "accepted": report["eventEvidence"]["acceptedCount"] = 2
            elif change == "class": report["perEventClass"]["beat"]["eventEvidence"]["count"] = 2
            else: report["aggregate"]["timing"]["predictedPerceptual"]["count"] = 0
            with self.assertRaises(ValueError):
                project(report)

    def test_unavailable_distribution_cannot_omit_producer_fields(self):
        for name in (*projection.STATISTICS, "basis", "count", "state"):
            report = produced([])
            report["perEventClass"]["beat"]["timing"]["command"].pop(name)
            with self.assertRaisesRegex(ValueError, "required producer fields"):
                project(report)

    def test_event_evidence_source_is_required_and_matches_state(self):
        for value in (None, "unknown", 123, {}, []):
            report = produced([event("beat")])
            report["eventEvidence"]["source"] = value
            with self.assertRaisesRegex(ValueError, "evidence source"):
                project(report)
        report = produced([event("beat")]); report["eventEvidence"].pop("source")
        with self.assertRaisesRegex(ValueError, "evidence source"):
            project(report)
        report = produced([]); report["eventEvidence"]["state"] = "unavailable"
        with self.assertRaisesRegex(ValueError, "evidence source"):
            project(report)
        report["eventEvidence"]["source"] = None
        self.assertEqual(project(report)["metrics"], {})

    def test_cli_binds_bytes_and_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / "input.json"; output = root / "output.json"
            source.write_text(json.dumps(produced([event("beat")])))
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            args = [sys.executable, str(ROOT / "tools/project_sync_metrics.py"), "--report", str(source),
                    "--source-commit", "1" * 40, "--run-id", "pair-01", "--perceptual-basis", "predicted",
                    "--output", str(output), "--expected-sha256"]
            bad = subprocess.run([*args, "0" * 64], capture_output=True)
            self.assertNotEqual(bad.returncode, 0); self.assertFalse(output.exists())
            good = subprocess.run([*args, digest], capture_output=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            original = output.read_bytes()
            duplicate = subprocess.run([*args, digest], capture_output=True)
            self.assertNotEqual(duplicate.returncode, 0); self.assertEqual(output.read_bytes(), original)

    def test_json_rejects_duplicate_keys(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            json.loads('{"version":1,"version":2}', object_pairs_hook=projection.unique_object)

    def test_cli_rejects_oversized_integer_without_traceback_or_output(self):
        report = produced([event("beat")])
        report["perEventClass"]["beat"]["timing"]["command"]["medianMs"] = 10 ** 400
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "input.json", root / "output.json"
            source.write_text(json.dumps(report))
            result = subprocess.run([
                sys.executable, str(ROOT / "tools/project_sync_metrics.py"),
                "--report", str(source), "--expected-sha256", hashlib.sha256(source.read_bytes()).hexdigest(),
                "--source-commit", "1" * 40, "--run-id", "pair-01",
                "--perceptual-basis", "predicted", "--output", str(output),
            ], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr.strip(), "Synchronization projection failed: ValueError")
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
