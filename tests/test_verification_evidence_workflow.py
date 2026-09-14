#!/usr/bin/env python3
"""Static safety checks for the sealed non-Android verify-v2 handoff."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/verify-v2.yml").read_text(encoding="utf-8")
PUBLISH_WORKFLOW = (ROOT / ".github/workflows/publish-release.yml").read_text(encoding="utf-8")


class VerificationEvidenceWorkflowTest(unittest.TestCase):
    def test_only_the_diagnostic_archive_uses_always(self):
        generic = WORKFLOW.index("name: lightforge-${{ env.LIGHTFORGE_RELEASE }}-verification\n")
        self.assertIn("if: always()", WORKFLOW[max(0, generic - 180):generic])
        content = WORKFLOW.index("name: lightforge-${{ env.LIGHTFORGE_RELEASE }}-verification-evidence-${{ github.run_id }}-${{ github.run_attempt }}")
        wrapper = WORKFLOW.index("name: lightforge-${{ env.LIGHTFORGE_RELEASE }}-verification-evidence-manifest-${{ github.run_id }}-${{ github.run_attempt }}")
        self.assertNotIn("if: always()", WORKFLOW[max(0, content - 220):content])
        self.assertNotIn("if: always()", WORKFLOW[max(0, wrapper - 220):wrapper])

    def test_fresh_receipts_are_purged_before_producers_and_sealed_after_candidate_upload(self):
        purge = WORKFLOW.index("Remove checked-in core receipts before fresh verification")
        tests = WORKFLOW.index("Production regression, diagnostics, and quality-tool suites")
        candidate = WORKFLOW.index("id: upload_candidate")
        seal = WORKFLOW.index("Seal success-only non-Android verification evidence")
        self.assertLess(purge, tests)
        self.assertLess(candidate, seal)
        for name in (
            "source-clock-verification.json",
            "regression-verification.json",
            "browser-verification.json",
            "background-ui-verification.json",
            "restore-preview-verification.json",
            "analysis-browser-verification.json",
            "native-inference-profile-equivalence.json",
            "native-mdx-comparison-verification.json",
            "native-mdx-downstream-verification.json",
            "native-mdx-downstream-native.json",
            "native-mdx-downstream-wasm.json",
            "native-recovery-results.json",
            "native-runtime-comparison-verification.json",
            "native-verification.json",
            "analysis-verification.json",
            "composer-verification.json",
            "light-verification.json",
            "movement-verification.json",
            "role-composer-verification.json",
            "role-reference-composer-verification.json",
        ):
            self.assertIn('"$receipt_root/' + name + '"', WORKFLOW)
        self.assertIn("--source-root \"$GITHUB_WORKSPACE\"", WORKFLOW)

    def test_restore_proof_runs_in_current_qa_directory_before_final_analysis(self):
        source_clock = WORKFLOW.index("test-source-clock.cjs")
        browser = WORKFLOW.index("node qa/release-${{ env.LIGHTFORGE_RELEASE }}/browser.cjs")
        background = WORKFLOW.index("node qa/release-${{ env.LIGHTFORGE_RELEASE }}/background-ui.cjs")
        restore_output = WORKFLOW.index('LIGHTFORGE_RESTORE_QA_OUTPUT="qa/release-$LIGHTFORGE_RELEASE"')
        restore = WORKFLOW.index("node qa/restore-preview/browser.cjs", restore_output)
        analysis_browser = WORKFLOW.index("node qa/release-${{ env.LIGHTFORGE_RELEASE }}/analysis-browser.cjs")
        native = WORKFLOW.index("name: Regenerate and verify same-session native evidence")
        final_analysis = WORKFLOW.index("verify-analysis.py", native)
        self.assertLess(source_clock, browser)
        self.assertLess(browser, background)
        self.assertLess(background, restore_output)
        self.assertLess(restore_output, restore)
        self.assertLess(restore, analysis_browser)
        self.assertLess(analysis_browser, native)
        self.assertLess(native, final_analysis)

    def test_candidate_sealing_covers_current_qa_restore_runner_and_package_metadata(self):
        for source in (
            '"qa/release-$LIGHTFORGE_RELEASE"',
            "qa/restore-preview/browser.cjs",
            "package.json",
            "package-lock.json",
            "'qa/release-' + os.environ['LIGHTFORGE_RELEASE']",
        ):
            self.assertIn(source, WORKFLOW)
        diff = WORKFLOW.index('git diff --exit-code "$GITHUB_SHA"')
        source_hashes = WORKFLOW.index("'git', 'ls-files', '-z', '--'")
        self.assertLess(diff, source_hashes)
        self.assertIn("import hashlib, json, os, subprocess, sys", WORKFLOW)

    def test_wrapper_binds_action_output_identity_and_candidate_retry_contract(self):
        for value in (
            "candidate_artifact_id", "candidate_artifact_digest", "candidate_identity_sha256",
            "candidate_run_id", "candidate_run_attempt", "candidate_evidence_session",
            "verification_evidence_artifact_id", "verification_evidence_wrapper_artifact_id",
            "steps.upload_candidate.outputs.artifact-id", "steps.upload_candidate.outputs.artifact-digest",
            "steps.upload_verification_evidence.outputs.artifact-id",
            "steps.upload_verification_evidence.outputs.artifact-digest",
            "write-wrapper", "--run-attempt \"$GITHUB_RUN_ATTEMPT\"",
        ):
            self.assertIn(value, WORKFLOW)

    def test_android_candidate_handoff_merges_exact_id_to_a_flat_root(self):
        download = WORKFLOW.index("Download the exact same-signed CI app and instrumentation")
        preflight = WORKFLOW.index("Assert exact flat sealed candidate handoff")
        emulator = WORKFLOW.index("Prepare Android 15 emulator")
        handoff = WORKFLOW[download:preflight]
        self.assertIn("artifact-ids:", handoff)
        self.assertIn("merge-multiple: true", handoff)
        self.assertIn("Candidate artifact extraction is not a flat exact inventory", WORKFLOW[preflight:emulator])
        self.assertLess(download, preflight)
        self.assertLess(preflight, emulator)
        flat = '--candidate-dir "$RUNNER_TEMP/lightforge-ci-candidate"'
        self.assertEqual(WORKFLOW.count(flat), 3)
        for command in (
            "python3 tools/run_android_background_tests.py",
            "python3 tools/run_android_diagnostics_tests.py",
            "python3 tools/android_evidence_manifest.py write",
        ):
            self.assertIn(command, WORKFLOW)


    def test_protected_publisher_reconstructs_all_allowlisted_model_families(self):
        sparse = PUBLISH_WORKFLOW.index("sparse-checkout:")
        restore = PUBLISH_WORKFLOW.index("Restore source-bound GAME and Deux graphs")
        publish = PUBLISH_WORKFLOW.index("python3 tools/publish_github_release.py")
        for value in (
            "research/upstream/deux",
            "torch==2.6.0",
            "-r tools/model-requirements.txt",
            "python3 tools/prepare_game.py",
            "python3 tools/prepare_deux.py",
        ):
            self.assertIn(value, PUBLISH_WORKFLOW)
        self.assertLess(sparse, restore)
        self.assertLess(restore, publish)

    def test_publisher_preflight_runs_before_every_repository_execution(self):
        preflight = PUBLISH_WORKFLOW.index("Establish immutable release source before privileged preparation")
        candidate_api = PUBLISH_WORKFLOW.index('gh api "repos/$GITHUB_REPOSITORY/actions/runs/$LIGHTFORGE_RELEASE_RUN_ID"')
        token_clear = PUBLISH_WORKFLOW.index("unset GH_TOKEN")
        worktree = PUBLISH_WORKFLOW.index("git worktree add --detach")
        restore = PUBLISH_WORKFLOW.index("Restore source-bound GAME and Deux graphs")
        bootstrap = PUBLISH_WORKFLOW.index("Bootstrap exact candidate toolchain")
        publish = PUBLISH_WORKFLOW.index("Verify provenance, reconstruct exact signed APK and publish")
        self.assertIn("persist-credentials: false", PUBLISH_WORKFLOW)
        self.assertIn("release_source_preflight.py", PUBLISH_WORKFLOW)
        self.assertIn('--checkout "$GITHUB_WORKSPACE"', PUBLISH_WORKFLOW)
        self.assertIn("Publisher checkout is not the exact verified candidate commit",
                      (ROOT / "tools/publish_github_release.py").read_text(encoding="utf-8"))
        for value in (
            "python3 -m pip install",
            "python3 tools/prepare_game.py",
            "python3 tools/prepare_deux.py",
            "prepare-musdb-fixtures.py",
            "python3 tools/bootstrap_toolchain.py",
        ):
            self.assertGreater(PUBLISH_WORKFLOW.index(value), preflight)
        self.assertLess(preflight, candidate_api)
        self.assertLess(candidate_api, token_clear)
        self.assertLess(token_clear, worktree)
        self.assertLess(worktree, restore)
        self.assertLess(restore, bootstrap)
        self.assertLess(bootstrap, publish)

if __name__ == "__main__":
    unittest.main()
