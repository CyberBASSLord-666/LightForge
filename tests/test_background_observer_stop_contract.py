"""Keep normal observer retirement cooperative and its executable regression mandatory."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BackgroundObserverStopContractTest(unittest.TestCase):
    def test_normal_stop_cannot_interrupt_status_file_reads(self):
        source = (ROOT/'tests/android/BackgroundInstrumentation.java').read_text()
        stop = source[source.index('private void stopBalancedObserver()'):source.index('private JSONObject balancedScreenOff()')]
        self.assertLess(stop.index('balancedObserverStopped=true'), stop.index('balancedObserver.join(5000)'))
        self.assertNotIn('.interrupt()', stop)
        self.assertIn('check(!balancedObserver.isAlive()', stop)
        self.assertIn('if(balancedObservationFailure!=null)throw new AssertionError', stop)
        observer = source[source.index('private void observeBalanced('):source.index('private void stopBalancedObserver()')]
        self.assertIn('catch(InterruptedException stopped){balancedObservationFailure=stopped;Thread.currentThread().interrupt();}', observer)
        self.assertIn('catch(Throwable error){balancedObservationFailure=error;}', observer)
        self.assertNotIn('ClosedByInterruptException', observer)

    def test_actual_method_nio_regression_runs_in_required_native_gate(self):
        suite = (ROOT/'tests/verify_native_release.py').read_text()
        self.assertIn("'BackgroundObserverStopTest'", suite)
        self.assertIn("ROOT/'tests/android/BackgroundInstrumentation.java'", suite)
        self.assertIn('tests + observer_host_stubs + passage_lifecycle_sources', suite)
        self.assertIn("run('BackgroundObserverStopTest', prepend_classpath=[observer_classes], timeout=30)", suite)
        test = (ROOT/'tests/BackgroundObserverStopTest.java').read_text()
        self.assertIn('getDeclaredMethod("stopBalancedObserver")', test)
        self.assertIn('pipe.source().read(bytes)', test)
        self.assertIn('stuckReadStillFailsAtFiveSeconds();', test)


if __name__ == '__main__':
    unittest.main()
