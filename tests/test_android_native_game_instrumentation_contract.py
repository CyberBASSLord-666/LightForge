"""Keep real Android GAME evidence distinct from host fixtures and speed claims."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tests/android/BackgroundInstrumentation.java'


class AndroidNativeGameInstrumentationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text()
        cls.game = cls.source[cls.source.index('private JSONObject nativeGameAndroid()'):
                              cls.source.index('private JSONObject gameResponse(')]

    def test_real_production_task_and_bridge_are_used(self):
        self.assertIn('new NativeGameTask(getTargetContext(),id)', self.game)
        self.assertIn('owner.new JobBridge(id,1L,null,null,task)', self.game)
        self.assertIn('owner.new JobBridge(id,1L,null,null)', self.game)
        self.assertIn('bridge.nativeGameRun(id,completeToken)', self.game)
        self.assertIn('receipt.put("nativeGame",nativeGameAndroid())', self.source)
        self.assertNotIn('Mock', self.game)

    def test_original_bundled_pcm_is_bounded_and_hash_bound(self):
        self.assertIn('getAssets().open("demo/glass-castle.wav")', self.source)
        self.assertIn('input.getShort()+input.getShort())/65536f', self.source)
        self.assertIn('6724721e8c1c4ac9ce532d46697393f8fafe81e7935f88399f05bc341115cedd', self.game)
        self.assertIn('first+=48*1024', self.source)
        for field in ('samples', 'sampleRate', 'language', 'seed', 'steps', 'model', 'completedPasses'):
            self.assertIn('complete.get', self.game)
            self.assertIn('"' + field + '"', self.game)

    def test_live_cancellation_precedes_last_diffusion_progress(self):
        self.assertIn('progress>=.18&&progress<.82', self.game)
        self.assertIn('field(engine,"activeRun")!=null', self.game)
        self.assertIn('state()!=null&&NativeDeux.INFERENCE_GATE.availablePermits()==0', self.game)
        self.assertIn('bridge.nativeGameCancel(id,cancelToken)', self.game)
        self.assertIn('cancelled.getInt("completedPasses")==1', self.game)
        self.assertIn('!cancelled.has("notes")', self.game)

    def test_unrounded_finite_notes_and_retirement_are_required(self):
        self.assertIn('midi==(double)(float)midi', self.game)
        self.assertIn('Math.abs(midi-Math.round(midi*100)/100.0)>1e-7', self.game)
        self.assertIn('end<=16.001', self.game)
        self.assertIn('gameRetired(task,"Completed GAME inference")', self.game)
        self.assertIn('gameRetired(task,"Cancelled GAME inference")', self.game)
        self.assertIn('executor.awaitTermination(15,java.util.concurrent.TimeUnit.SECONDS)&&task.isRetired()', self.game)

    def test_receipt_does_not_claim_quality_speed_or_os_started_service(self):
        self.assertIn('test-only service-owner attachment, not an OS service-start, comparative-quality, speedup or physical-device claim', self.game)
        self.assertIn('.put("scope","Android emulator:', self.game)
        self.assertIn('gameDenied(stale.nativeGameBegin', self.game)
        self.assertIn('gameDenied(bridge.nativeGameBegin(foreign', self.game)
        self.assertIn('gameDenied(legacy.nativeGameAvailability', self.game)


if __name__ == '__main__':
    unittest.main()
