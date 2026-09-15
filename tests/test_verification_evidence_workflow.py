#!/usr/bin/env python3
"""Static safety checks for the sealed non-Android verify-v2 handoff."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/verify-v2.yml").read_text(encoding="utf-8")
PUBLISH_WORKFLOW = (ROOT / ".github/workflows/publish-release.yml").read_text(encoding="utf-8")


def _publisher_job(name):
    start = PUBLISH_WORKFLOW.index("\n  " + name + ":\n")
    next_job = re.search(r"\n  [a-zA-Z_][a-zA-Z0-9_-]*:\n", PUBLISH_WORKFLOW[start + 1:])
    end = start + 1 + next_job.start() if next_job else len(PUBLISH_WORKFLOW)
    return PUBLISH_WORKFLOW[start:end]


def _publisher_step(job, name):
    start = job.index("      - name: " + name + "\n")
    next_step = re.search(r"\n      - (?:name|uses):", job[start:])
    end = start + next_step.start() if next_step else len(job)
    return job[start:end]


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


    def test_reconstruction_is_read_only_and_separate_from_protected_publisher(self):
        reconstruct = _publisher_job("reconstruct")
        publish = _publisher_job("publish")
        self.assertIn("    permissions:\n      contents: read\n      actions: read\n", reconstruct)
        self.assertNotIn("environment:", reconstruct)
        self.assertNotIn("secrets.", reconstruct)
        self.assertNotIn("contents: write", reconstruct)
        self.assertIn("    needs: reconstruct\n", publish)
        self.assertIn("    environment: lightforge-release-quality\n", publish)
        self.assertIn("    permissions:\n      contents: write\n      actions: read\n", publish)
        for job in (reconstruct, publish):
            self.assertIn("    runs-on: ubuntu-latest\n", job)
            self.assertIn("uses: actions/checkout@", job)
            self.assertIn("persist-credentials: false", job)
            self.assertIn('test "$LIGHTFORGE_REF_PROTECTED" = "true"', job)
        for command in (
            "python3 -m pip install", "torch==2.6.0", "-r tools/model-requirements.txt",
            "python3 tools/prepare_game.py", "python3 tools/prepare_deux.py", "prepare-musdb-fixtures.py",
        ):
            self.assertIn(command, reconstruct)
            self.assertNotIn(command, publish)
        self.assertNotIn("bootstrap_toolchain.py", publish)
        self.assertIn("research/upstream/deux", reconstruct)
        self.assertLess(reconstruct.index("release_source_preflight.py"), reconstruct.index("python3 -m pip install"))
        self.assertLess(reconstruct.index("prepare-musdb-fixtures.py"), reconstruct.index("release_material_handoff.py write"))
        upload = _publisher_step(reconstruct, "Upload immutable data-only material handoff")
        self.assertIn("path: ${{ runner.temp }}/lightforge-release-materials.zip\n", upload)
        self.assertIn("if-no-files-found: error", upload)
        self.assertNotIn("if: always()", upload)

    def test_fresh_publisher_binds_exact_same_run_artifact_and_flat_data_inventory(self):
        reconstruct = _publisher_job("reconstruct")
        publish = _publisher_job("publish")
        identity = _publisher_step(publish, "Validate exact same-run material artifact identity")
        download = _publisher_step(publish, "Download and verify exact material artifact before extraction")
        install = _publisher_step(publish, "Install only source-pinned material bytes")
        self.assertIn("artifact_id: ${{ steps.upload_materials.outputs.artifact-id }}", reconstruct)
        self.assertIn("artifact_digest: ${{ steps.upload_materials.outputs.artifact-digest }}", reconstruct)
        self.assertIn("artifact_name: lightforge-release-materials-${{ github.run_id }}-${{ github.run_attempt }}", reconstruct)
        for value in (
            "MATERIAL_ARTIFACT_ID: ${{ needs.reconstruct.outputs.artifact_id }}",
            "MATERIAL_ARTIFACT_DIGEST: ${{ needs.reconstruct.outputs.artifact_digest }}",
            "MATERIAL_ARTIFACT_NAME: ${{ needs.reconstruct.outputs.artifact_name }}",
            'gh api "repos/$GITHUB_REPOSITORY/actions/artifacts/$MATERIAL_ARTIFACT_ID"',
            'record.get("id") == int(os.environ["MATERIAL_ARTIFACT_ID"])',
            'record.get("digest") == expected_digest',
            '.removeprefix("sha256:")',
            'record.get("expired") is False',
            'record.get("name") == os.environ["MATERIAL_ARTIFACT_NAME"]',
            'run.get("id") == int(os.environ["GITHUB_RUN_ID"])',
            'run.get("head_sha") == os.environ["GITHUB_SHA"]',
            'run.get("head_branch") == "main"',
        ):
            self.assertIn(value, identity)
        for value in (
            "MATERIAL_ARTIFACT_ID: ${{ needs.reconstruct.outputs.artifact_id }}",
            "MATERIAL_ARTIFACT_DIGEST: ${{ needs.reconstruct.outputs.artifact_digest }}",
            '"/actions/artifacts/" + artifact_id + "/zip"',
            'root.mkdir(exist_ok=False)', 'archive_path.open("xb")',
            "if total > limit:", "if process.wait() != 0:",
            "if digest.hexdigest() != checksum:",
            "Downloaded material artifact digest differs from Actions metadata",
            'len(infos) != 1 or infos[0].filename != "lightforge-release-materials.zip"',
            "info.flag_bits & 1", "stat.S_IFREG", "0 < info.file_size <= limit",
            '(root / info.filename).open("xb")', "if count > info.file_size:", "if count != info.file_size:",
        ):
            self.assertIn(value, download)
        self.assertLess(download.index("if digest.hexdigest() != checksum:"), download.index("zipfile.ZipFile"))
        self.assertNotIn("extractall", download)
        self.assertNotIn("actions/download-artifact@", publish)
        for value in (
            'len(entries) != 1', 'entries[0].name != "lightforge-release-materials.zip"',
            "entries[0].is_symlink()", "not entries[0].is_file()",
            "Material artifact extraction is not a flat exact inventory",
            "python3 -E -S tools/release_material_handoff.py install",
            '--source-commit "$LIGHTFORGE_RELEASE_SOURCE_COMMIT"',
        ):
            self.assertIn(value, install)
        self.assertLess(publish.index(identity), publish.index(download))
        self.assertLess(publish.index(download), publish.index(install))

    def test_inline_python_is_isolated_and_candidate_preflight_precedes_repository_execution(self):
        for name in ("reconstruct", "publish"):
            job = _publisher_job(name)
            step = _publisher_step(job, "Establish immutable release source before repository execution")
            self.assertIn("GH_TOKEN: ${{ github.token }}", step)
            self.assertEqual(step.count("python3 -I -S - "), 2)
            self.assertNotIn("python3 - ", step)
            candidate_api = step.index('gh api "repos/$GITHUB_REPOSITORY/actions/runs/$LIGHTFORGE_RELEASE_RUN_ID"')
            token_clear = step.index("unset GH_TOKEN")
            worktree = step.index("git worktree add --detach")
            preflight = step.index('python3 -E -S "$source_root/tools/release_source_preflight.py"')
            self.assertLess(candidate_api, token_clear)
            self.assertLess(token_clear, worktree)
            self.assertLess(worktree, preflight)
            self.assertIn('--checkout "$GITHUB_WORKSPACE"', step)
            self.assertNotRegex(step[:token_clear], r"python3 (?!-I -S - )")
        identity = _publisher_step(_publisher_job("publish"), "Validate exact same-run material artifact identity")
        self.assertEqual(identity.count("python3 -I -S - "), 2)
        self.assertNotRegex(identity, r"python3 (?!-I -S - )")
        download = _publisher_step(_publisher_job("publish"), "Download and verify exact material artifact before extraction")
        self.assertIn("GH_TOKEN: ${{ github.token }}", download)
        self.assertEqual(download.count("python3 -I -S - "), 1)
        self.assertNotRegex(download, r"python3 (?!-I -S - )")
        self.assertIn("Publisher checkout is not the exact verified candidate commit",
                      (ROOT / "tools/publish_github_release.py").read_text(encoding="utf-8"))

    def test_publisher_provisions_pinned_tools_and_rechecks_source_before_secret(self):
        publish = _publisher_job("publish")
        provision = _publisher_step(publish, "Provision independently pinned APK verification tools")
        recheck = _publisher_step(publish, "Recheck immutable publisher source and installed materials")
        final = _publisher_step(publish, "Verify provenance, reconstruct exact signed APK and publish")
        self.assertNotIn("python3", provision)
        self.assertNotIn("$LIGHTFORGE_RELEASE_SOURCE/", provision)
        self.assertIn('test ! -e "$toolchain"', provision)
        for archive, extract in (("jdk17.tar.gz", "tar -xzf"), ("build-tools.zip", "unzip -q")):
            self.assertRegex(provision, r"stat -c '%s' [^\n]+" + re.escape(archive) + r"[^\n]+[0-9]+")
            hash_line = re.search(r"'[0-9a-f]{64}' [^\n]+" + re.escape(archive) + r"[^\n]+sha256sum -c", provision)
            self.assertIsNotNone(hash_line)
            self.assertLess(hash_line.start(), provision.index(extract))
        self.assertIn('git diff --exit-code "$LIGHTFORGE_RELEASE_SOURCE_COMMIT" -- .github tools web android version.json', recheck)
        self.assertIn("python3 -E -S tools/release_material_handoff.py verify", recheck)
        self.assertIn("for executable in aapt2 apksigner zipalign", recheck)
        self.assertLess(publish.index(provision), publish.index(recheck))
        self.assertLess(publish.index(recheck), publish.index(final))
        self.assertIn('python3 -I -S -m json.tool "$target" > /dev/null', final)
        self.assertIn("python3 -E -S tools/publish_github_release.py", final)

if __name__ == "__main__":
    unittest.main()
