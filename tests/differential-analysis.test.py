import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("differential", ROOT / "tools/differential_analysis.py")
differential = importlib.util.module_from_spec(spec)
spec.loader.exec_module(differential)


def identity(implementation="baseline"):
    return {
        "audio_sha256": "a" * 64,
        "analysis_configuration_sha256": "b" * 64,
        "model_manifest_sha256": "c" * 64,
        "vehicle_profile_sha256": "d" * 64,
        "fseq_configuration_sha256": "e" * 64,
        "implementation_id": implementation,
    }


def event(event_id, timestamp, salience, event_type="vocal.syllable", source="lead_vocal", confidence=0.9):
    return {
        "id": event_id,
        "timestamp_seconds": timestamp,
        "duration_seconds": 0.10,
        "event_type": event_type,
        "source": source,
        "confidence": confidence,
        "salience": salience,
        "tier": "primary" if salience >= 0.70 else "secondary",
        "section_id": "section-a",
    }


def command(command_id, event_id, timestamp, output="left-signature", salience=None):
    value = {
        "id": command_id,
        "event_id": event_id,
        "timestamp_seconds": timestamp,
        "duration_seconds": 0.10,
        "output_id": output,
        "command_type": "pulse",
        "perceptual_timestamp_seconds": timestamp + 0.02,
    }
    if salience is not None:
        value["salience"] = salience
    return value


def timing(timing_id, command_id, intended, command_time, realized, frame):
    return {
        "id": timing_id,
        "command_id": command_id,
        "intended_perceptual_timestamp_seconds": intended,
        "command_timestamp_seconds": command_time,
        "realized_perceptual_timestamp_seconds": realized,
        "frame_index": frame,
    }


def report(implementation="baseline"):
    events = [
        event("evt-vocal-001", 1.0, 0.95),
        event("evt-section-001", 5.0, 0.90, "structure.section_boundary", "mix"),
        event("evt-removed-001", 7.0, 0.91, "bass.note", "bass"),
    ]
    commands = [
        command("cmd-vocal-001", "evt-vocal-001", 0.98),
        command("cmd-section-001", "evt-section-001", 4.98, "right-signature"),
        command("cmd-removed-001", "evt-removed-001", 6.98),
    ]
    return {
        "schema_version": 1,
        "identity": identity(implementation),
        "semantic_events": events,
        "choreography_commands": commands,
        "collision_resolutions": [
            {
                "id": "collision-vocal-001",
                "event_id": "evt-vocal-001",
                "status": "resolved",
                "salience": 0.95,
                "preferred_output_id": "left-signature",
                "realized_output_id": "left-signature",
                "reason": "direct",
            }
        ],
        "fseq_timing": [
            timing("fseq-vocal-001", "cmd-vocal-001", 1.0, 0.98, 1.0, 49),
            timing("fseq-section-001", "cmd-section-001", 5.0, 4.98, 5.0, 249),
            timing("fseq-removed-001", "cmd-removed-001", 7.0, 6.98, 7.0, 349),
        ],
    }


class DifferentialAnalysisTest(unittest.TestCase):
    def candidate(self):
        candidate = report("candidate")
        candidate["semantic_events"] = [
            event("evt-vocal-001", 1.03, 0.82, confidence=0.82),
            event("evt-section-001", 5.04, 0.90, "structure.section_boundary", "mix"),
            event("evt-added-001", 8.0, 0.40, "drum.kick", "drums"),
        ]
        candidate["choreography_commands"] = [
            command("cmd-vocal-001", "evt-vocal-001", 1.01, "right-signature"),
            command("cmd-section-001", "evt-section-001", 5.02, "right-signature"),
            command("cmd-added-001", "evt-added-001", 8.0, "brakes"),
        ]
        candidate["collision_resolutions"] = [
            {
                "id": "collision-vocal-001",
                "event_id": "evt-vocal-001",
                "status": "unresolved",
                "salience": 0.95,
                "preferred_output_id": "left-signature",
                "reason": "blocked",
            }
        ]
        candidate["fseq_timing"] = [
            timing("fseq-vocal-001", "cmd-vocal-001", 1.03, 1.01, 1.04, 50),
            timing("fseq-section-001", "cmd-section-001", 5.04, 5.02, 5.04, 251),
            timing("fseq-added-001", "cmd-added-001", 8.0, 8.0, 8.0, 400),
        ]
        return candidate

    def test_reports_all_required_change_categories(self):
        result = differential.compare(report(), self.candidate())
        self.assertEqual("COMPARABLE", result["status"])
        self.assertEqual(["evt-added-001"], [item["id"] for item in result["semantic_events"]["added"]])
        self.assertEqual(["evt-removed-001"], [item["id"] for item in result["semantic_events"]["removed"]])
        self.assertEqual(["evt-section-001", "evt-vocal-001"], [item["id"] for item in result["semantic_events"]["timestamps_shifted"]])
        self.assertEqual(["evt-vocal-001"], [item["id"] for item in result["semantic_events"]["confidence_changed"]])
        self.assertEqual(["evt-section-001"], [item["id"] for item in result["semantic_events"]["section_boundaries"]["changed"]])
        self.assertTrue(result["semantic_events"]["salience_rank_changes"])
        self.assertEqual("right-signature", result["choreography_commands"]["actuator_assignment_changes"][0]["candidate_output_id"])
        self.assertEqual("unresolved", result["collision_resolutions"]["resolution_changes"][0]["changes"]["status"]["candidate"])
        timing_by_id = {item["id"]: item for item in result["fseq_timing"]["timing_differences"]}
        self.assertAlmostEqual(30.0, timing_by_id["fseq-vocal-001"]["command_timestamp_delta_milliseconds"])
        kinds = {item["kind"] for item in result["release_review_items"]}
        self.assertIn("removed_high_salience_event", kinds)
        self.assertIn("shifted_high_salience_event", kinds)
        self.assertIn("unresolved_high_salience_collision", kinds)

    def test_is_deterministic_when_input_arrays_are_reordered(self):
        baseline, candidate = report(), self.candidate()
        expected = json.dumps(differential.compare(baseline, candidate), sort_keys=True, allow_nan=False)
        for field in ("semantic_events", "choreography_commands", "collision_resolutions", "fseq_timing"):
            baseline[field] = list(reversed(baseline[field]))
            candidate[field] = list(reversed(candidate[field]))
        actual = json.dumps(differential.compare(baseline, candidate), sort_keys=True, allow_nan=False)
        self.assertEqual(expected, actual)

    def test_non_finite_or_private_unknown_input_fails_closed(self):
        invalid = report()
        invalid["semantic_events"][0]["confidence"] = float("nan")
        with self.assertRaises(differential.DifferentialValidationError):
            differential.compare(invalid, report())
        invalid = report()
        invalid["lyrics"] = "not allowed"
        with self.assertRaises(differential.DifferentialValidationError):
            differential.compare(invalid, report())

    def test_dangling_references_and_duplicate_ids_fail_closed(self):
        invalid = report()
        invalid["choreography_commands"][0]["event_id"] = "evt-missing-001"
        with self.assertRaises(differential.DifferentialValidationError):
            differential.compare(invalid, report())
        invalid = report()
        invalid["semantic_events"].append(copy.deepcopy(invalid["semantic_events"][0]))
        with self.assertRaises(differential.DifferentialValidationError):
            differential.compare(invalid, report())

    def test_identity_difference_is_incomparable(self):
        candidate = self.candidate()
        candidate["identity"]["audio_sha256"] = "f" * 64
        with self.assertRaises(differential.IncomparableReportsError):
            differential.compare(report(), candidate)

    def test_cli_writes_machine_readable_invalid_input_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            output = root / "out.json"
            baseline.write_text('{"schema_version": NaN}', encoding="utf-8")
            candidate.write_text(json.dumps(report()), encoding="utf-8")
            self.assertEqual(2, differential.main(["--baseline", str(baseline), "--candidate", str(candidate), "--output", str(output)]))
            error = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("INVALID_INPUT", error["status"])
            self.assertNotIn("NaN", json.dumps(error))


if __name__ == "__main__":
    unittest.main()
