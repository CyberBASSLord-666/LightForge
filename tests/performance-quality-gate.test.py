import importlib.util, json, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("gate",ROOT/"tools/performance_quality_gate.py")
gate=importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)

def report(runtime, vocal=.95):
    return {"runs":[{"track_id":"vocal-rock","metrics":{"performance":{"total_wall_clock_seconds":runtime},"quality":{"vocal_alignment_f1":vocal,"beat_f1":.96,"downbeat_f1":.94,"bass_event_f1":.92,"structural_event_recall":.91,"high_salience_coverage":.98,"perceptual_sync_p95_ms":18,"actuator_feasibility":1,"high_salience_collision_loss":0}}}]}

class GateTest(unittest.TestCase):
    def setUp(self): self.policy=json.loads((ROOT/"qa/performance-gate-policy.json").read_text())
    def test_target_pass(self): self.assertEqual("PASS_TARGET",gate.compare(report(100),report(24),self.policy)["status"])
    def test_partial_is_honest(self): self.assertEqual("PASS_PARTIAL",gate.compare(report(100),report(60),self.policy)["status"])
    def test_critical_regression_blocks(self):
        result=gate.compare(report(100),report(20,.90),self.policy)
        self.assertEqual("FAIL",result["status"]); self.assertFalse(result["production_ready"])
    def test_percentile_interpolates(self): self.assertEqual(3.7,gate.percentile([1,2,3,4],.9))

if __name__=="__main__": unittest.main()
