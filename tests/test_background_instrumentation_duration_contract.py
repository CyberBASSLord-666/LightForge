#!/usr/bin/env python3
"""Keep Android semantic validation anchored to the frozen analysis input clock."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"tests"/"android"/"BackgroundInstrumentation.java"


class BackgroundInstrumentationDurationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=SOURCE.read_text(encoding="utf-8")
        cls.compact=re.sub(r"\s+","",cls.source)

    def test_balanced_analysis_uses_its_frozen_request_duration(self):
        self.assertIn(
            'checkCanonicalSemanticAnalysis(music,frozen.getDouble("duration"),"Balancedfixture");',
            self.compact,
        )

    def test_studio_duration_is_captured_before_the_job_can_finish(self):
        start=self.source.index('String id=fixture("Background audio");')
        validation=self.source.index(
            'checkCanonicalSemanticAnalysis(saved.getJSONObject("music"),sourceDuration,"Actual analysis");',
            start,
        )
        actual=self.source[start:validation]
        self.assertIn(
            'double sourceDuration=AnalysisJobStore.request(files,job.getString("id")).getDouble("duration");',
            actual,
        )
        self.assertLess(
            actual.index('double sourceDuration='),
            actual.index('JSONObject completed=waitTerminal'),
        )

    def test_canonical_validation_keeps_the_external_source_clock(self):
        self.assertIn(
            "AnalysisJobStore.validateCheckpoint(music,sourceDuration);",
            self.source,
        )

    def test_saved_project_envelope_is_not_used_as_the_source_clock(self):
        self.assertNotIn('saved.getDouble("duration")',self.source)


if __name__=="__main__":
    unittest.main()
