# Configure the protected release-quality authority

For **2.2.5 / code 20205, 2.3.0 / code 20300 and 2.3.1 / code 20301**, these external qualification inputs are optional under the owner-approved `automated_verification_only` publication declarations. No policy/corpus/review bundle needs to be supplied to publish these versions. The 2.3.0 and 2.3.1 declarations follow the owner's explicit requests to improve and continue musical intelligence and inference work, and publish when ready without user-supplied measurements. Each declaration authorizes only its exact version/code pair. Comparative claims remain limited to actual recorded test scope; the 75% whole-analysis target, general musical-quality non-regression and hardware measurements remain unverified. Existing protected-main and deployment controls, full host/Android verification, original-key signing and package integrity checks remain mandatory. The following setup applies when running the separate strict benchmark qualification; its thresholds and evidence requirements are unchanged.

This setup authorizes one exact acceptance policy and locked corpus. It does
not qualify a release, generate benchmark observations, or provide human
perceptual review. Physical phone and Tesla observations remain optional.
The complete acceptance contract is in
[PERFORMANCE_QUALITY_GATE.md](PERFORMANCE_QUALITY_GATE.md).

## Public authority identity

The owner-controlled policy identity is separate from the original Android
update signer and from the blinded-review verifier:

| Field | Value |
| --- | --- |
| Authority ID | `lightforge-owner-policy-2026-09` |
| Protocol | `lightforge-release-policy-authority-v1` |
| Algorithm | `ed25519` |
| Public key, base64 | `gsj+FZKu+e/5qv74QWB+g4oBNGHpQ5IaHXIP37Co1sU=` |
| Public-key SHA-256 | `04674bb0fba8986e9eece3ced056d145ee9fa377251c33f0e3e4b373102fdca7` |

The gate resolves that key only from `RELEASE_POLICY_AUTHORITY_KEYS` in
reviewed source. Retain the private PEM in the owner's private backup, outside
the checkout and CI. Never put it in a GitHub secret, artifact, policy JSON,
publication request, or release asset. No Android signing key is changed by
this setup.

## Prepare and validate the three protected files

Use real approved inputs: `performance-gate-policy.json`,
`locked-corpus-manifest.json`, and `release-policy-attestation.json`.
The policy must pin the authority above, the actual runtime profile and the
independent blinded-review verifier. The manifest must identify at least 16
distinct licensed tracks, required coverage, genuine annotations and golden
outputs. Do not turn the checked-in templates into evidence by changing their
flags or replacing their placeholders with invented hashes.

Run the helper from the reviewed source version that will execute the gate.
It uses the gate's canonical policy digest, including the compiled metric
contract, and validates the complete corpus before signing. Python 3.12+ and
an OpenSSL build with Ed25519 support are required. Keep the private PEM mode
`0600`; signing refuses a key inside the repository or one that does not match
the source-pinned public key. The output path must not already exist.

```bash
set -euo pipefail
set +x
umask 077
LIGHTFORGE_QUALITY_DIR=/absolute/private/release-quality
LIGHTFORGE_POLICY_KEY=/absolute/private/release-policy-authority.pem

python3 tools/release_policy_setup.py sign \
  --policy "$LIGHTFORGE_QUALITY_DIR/performance-gate-policy.json" \
  --manifest "$LIGHTFORGE_QUALITY_DIR/locked-corpus-manifest.json" \
  --private-key "$LIGHTFORGE_POLICY_KEY" \
  --output "$LIGHTFORGE_QUALITY_DIR/release-policy-attestation.json"

python3 tools/release_policy_setup.py validate \
  --policy "$LIGHTFORGE_QUALITY_DIR/performance-gate-policy.json" \
  --manifest "$LIGHTFORGE_QUALITY_DIR/locked-corpus-manifest.json" \
  --attestation "$LIGHTFORGE_QUALITY_DIR/release-policy-attestation.json"
```

Signing is the policy authority's approval of those exact inputs. Issue that
signature only after their approval. The helper prints hashes and status,
never input JSON or private-key bytes. It rejects malformed/duplicate-key
JSON, oversized environment-secret input, a relaxed policy, incomplete
corpus, unknown authority, wrong signing key, and a mismatched signature.
`qualification_status: not_evaluated` is intentional: independent measured
baseline/candidate evidence and authenticated human review are still required.

## Preserve and configure GitHub protections

Use an owner/admin GitHub session for repository settings. The managed source
connector cannot administer branch protections, environments or secrets.
Record the existing protections before changing them; a denied API read is
not evidence that settings are absent. These read-only commands expose
configuration metadata, not secret values:

```bash
LIGHTFORGE_REPOSITORY=CyberBASSLord-666/LightForge
gh api "repos/$LIGHTFORGE_REPOSITORY/branches/main"
gh api "repos/$LIGHTFORGE_REPOSITORY/branches/main/protection"
gh api --paginate "repos/$LIGHTFORGE_REPOSITORY/rulesets?includes_parents=true&per_page=100"
gh api "repos/$LIGHTFORGE_REPOSITORY/environments/lightforge-release-quality"
gh secret list --repo "$LIGHTFORGE_REPOSITORY" --env lightforge-release-quality
```

In repository **Settings → Branches** or **Settings → Rules → Rulesets**,
ensure an active protection applies to `main`. Preserve existing required
checks, approvals, restrictions, code-owner rules and bypass restrictions.
If protection is absent, configure reviewed pull-request changes and disallow
force pushes/deletion; choose the required review/check policy explicitly in
the settings review. The release workflow requires GitHub's protected-ref
result to be true. Its own full CI and source checks remain mandatory even
when a status check is not marked required for merging. Do not submit a
generic replacement branch-protection body: GitHub accepts `null` to disable
existing required checks, so a blanket PUT can remove stronger protection.
[GitHub branch-protection API](https://docs.github.com/en/rest/branches/branch-protection#update-branch-protection).

In **Settings → Environments**, open or create
`lightforge-release-quality`. Restrict deployment to protected branches or
select the exact **Branch** pattern `main`. Preserve existing narrower rules,
required reviewers, prevention of self-review, wait timers, custom protection
rules and administrator-bypass restrictions. Resolve an existing rule that
excludes `main` as an explicit configuration change; do not delete/recreate
the environment. If it has required reviewers, their deployment approval is
part of the existing workflow. A workflow-created environment can otherwise
exist with no protection or secrets, so its name alone proves nothing.
[GitHub environment configuration](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

## Install the validated protected bundle

After the local validation succeeds and the settings above are configured,
use the owner/admin session to set these **environment secrets**. The file
redirections preserve JSON newlines and keep values out of command arguments.
Do not use shell tracing or `--body "$(cat ...)"`.
[GitHub CLI secret input](https://cli.github.com/manual/gh_secret_set).

```bash
set -euo pipefail
set +x
LIGHTFORGE_REPOSITORY=CyberBASSLord-666/LightForge
LIGHTFORGE_QUALITY_DIR=/absolute/private/release-quality

python3 tools/release_policy_setup.py validate \
  --policy "$LIGHTFORGE_QUALITY_DIR/performance-gate-policy.json" \
  --manifest "$LIGHTFORGE_QUALITY_DIR/locked-corpus-manifest.json" \
  --attestation "$LIGHTFORGE_QUALITY_DIR/release-policy-attestation.json"

gh secret set LIGHTFORGE_RELEASE_POLICY_JSON \
  --repo "$LIGHTFORGE_REPOSITORY" --env lightforge-release-quality \
  < "$LIGHTFORGE_QUALITY_DIR/performance-gate-policy.json"
gh secret set LIGHTFORGE_RELEASE_CORPUS_MANIFEST_JSON \
  --repo "$LIGHTFORGE_REPOSITORY" --env lightforge-release-quality \
  < "$LIGHTFORGE_QUALITY_DIR/locked-corpus-manifest.json"
gh secret set LIGHTFORGE_RELEASE_POLICY_ATTESTATION_JSON \
  --repo "$LIGHTFORGE_REPOSITORY" --env lightforge-release-quality \
  < "$LIGHTFORGE_QUALITY_DIR/release-policy-attestation.json"

gh secret list --repo "$LIGHTFORGE_REPOSITORY" --env lightforge-release-quality
gh api "repos/$LIGHTFORGE_REPOSITORY/branches/main" --jq '.protected'
```

GitHub does not return secret values for readback. Record the local validated
policy/corpus hashes and check the gate report uses them. Do not run a gate
between these three uploads; if an upload fails, finish installing the exact
validated bundle before dispatch. Do not replace existing values with an
unsigned or partially configured template.

## Qualify the exact release candidate

Collect the controlled, paired baseline/candidate observations with the fixed
corpus and runtime profile. Obtain the separate authenticated blinded review
from at least three human reviewers. Preserve five or more pairs per track,
the 99% confidence floor, the 75% per-track total-time reduction target, and
all quality/resource requirements. An authority signature does not assert
that measurements exist or that those targets passed.

After the exact candidate's full `verify-v2.yml` run succeeds, dispatch
**Performance quality gate** from `main` with complete baseline artifact/run,
candidate artifact/run, release candidate run, and `release_version` matching
the exact candidate's `version.json`. Complete any existing deployment-review step. The release comparison
must report `PASS_TARGET` and `production_ready: true`, with its receipt bound
to the exact candidate source, tree, APK and artifact metadata. Unit-job
success or an aggregation job alone is not qualification.

Then follow [BUILD.md](../BUILD.md) for candidate preparation, original-key APK
signing, delta creation and publication. The public, non-draft `v<version>`
release must contain the verified original-signed APK, checksum, release notes
and verification report. Physical validation may remain explicitly unverified.
