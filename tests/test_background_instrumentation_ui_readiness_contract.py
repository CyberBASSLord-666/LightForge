#!/usr/bin/env python3
"""Keep Android preview readiness bounded, recovery-bound, and observable."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests" / "android" / "BackgroundInstrumentation.java"


class BackgroundInstrumentationUiReadinessContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.compact = re.sub(r"\s+", "", cls.source)
        start = cls.source.index("private final class UiReadiness")
        end = cls.source.index("private void backgroundAndDoze", start)
        cls.readiness = cls.source[start:end]
        cls.readiness_compact = re.sub(r"\s+", "", cls.readiness)

    def test_non_ready_javascript_poll_is_rate_limited(self):
        self.assertIn("UI_READINESS_POLL_MS=100L", self.compact)
        self.assertIn("target.postDelayed(this,UI_READINESS_POLL_MS)", self.readiness_compact)
        self.assertIn("if(waitingForJavascriptResponse())return;", self.readiness_compact)
        self.assertNotIn("postOnAnimation", self.readiness)

    def test_lost_callback_cannot_rebind_without_exact_production_recovery(self):
        self.assertIn("probe.recoverMissingJavascriptCallback();", self.source)
        self.assertIn("SystemClock.elapsedRealtime()-requestedAt<UI_JAVASCRIPT_CALLBACK_BUDGET_MS", self.readiness_compact)
        self.assertIn("current!=requested", self.readiness_compact)
        self.assertIn('recoveryCount==recoveryCountAtStart+1', self.readiness_compact)
        self.assertIn('recovery.startsWith(prefix)', self.readiness_compact)
        for reason in ("callback-stall", "phase-stall", "renderer-gone"):
            self.assertIn(f'reason.startsWith("{reason}")', self.readiness_compact)

    def test_recovery_retries_only_on_main_thread_after_invalidating_old_callback(self):
        watchdog = self.readiness[
            self.readiness.index("void recoverMissingJavascriptCallback")
            : self.readiness.index("private void schedulePoll")
        ]
        self.assertNotIn(".removeCallbacks(", watchdog)
        self.assertNotIn(".postDelayed(", watchdog)
        self.assertIn("clearJavascriptResponse();", watchdog)
        self.assertIn("watchdogMain.post(this);", watchdog)

    def test_renderer_gone_regression_requires_rebind_frame_and_ack(self):
        self.assertIn(
            'awaitUiReady(()->check(owner.handlePreviewRenderProcessGone(stalled,false)',
            self.compact,
        )
        self.assertIn(
            'lastUiReadiness!=null&&lastUiReadiness.optBoolean("completedRestoreRebound")',
            self.compact,
        )
        self.assertIn(
            'requireCompletedRestoreAck(completed,"Active renderer-gone replacement")',
            self.source,
        )
        self.assertIn(
            'requireCompletedRestoreAck(completed,"Reopened Activity")',
            self.source,
        )
        self.assertIn('firstFrameCommitted', self.readiness)

    def test_failure_evidence_is_bounded_sanitized_and_only_exact_replacement_gets_a_new_window(self):
        self.assertIn("UI_READINESS_INITIAL_BUDGET_MS=45000L", self.compact)
        self.assertIn("UI_READINESS_RECOVERY_BUDGET_MS=45000L", self.compact)
        self.assertIn("volatilelongdeadline=began+UI_READINESS_INITIAL_BUDGET_MS", self.readiness_compact)
        self.assertIn("!reboundCompletedRestore", self.readiness_compact)
        self.assertIn(
            "deadline=Math.max(deadline,SystemClock.elapsedRealtime()+UI_READINESS_RECOVERY_BUDGET_MS)",
            self.readiness_compact,
        )
        self.assertLess(
            self.readiness.index('check(current(),"Preview changed while awaiting its first frame")'),
            self.readiness.index('check(SystemClock.elapsedRealtime()<deadline,"Preview JavaScript initialization exceeded its bounded readiness window")'),
        )
        self.assertIn("private void emitFailureDiagnostics()", self.source)
        self.assertIn("AppDiagnostics.flush(1000)", self.source)
        self.assertIn('field(AppDiagnostics.class,"journal")', self.source)
        self.assertIn("journal.snapshot(snapshot)", self.source)
        self.assertIn("bytes.length-64*1024", self.source)
        self.assertIn("LIGHTFORGE_DIAGNOSTICS_BEGIN", self.source)
        self.assertIn("LIGHTFORGE_DIAGNOSTICS_END", self.source)
        failure = self.source[self.source.rindex("}catch(Throwable error){"):]
        self.assertIn("emitFailureDiagnostics();", failure)
        for name in ("previewGraphicsInitialized", "previewLoadStarted", "previewLoadDeferred", "restorePhase", "restoreSequence"):
            self.assertIn(name + ":", self.readiness)


if __name__ == "__main__":
    unittest.main()
