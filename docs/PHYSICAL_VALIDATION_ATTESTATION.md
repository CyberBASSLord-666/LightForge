# Optional physical validation evidence

A production release does not require physical phone or Tesla observations.
The sealed Android emulator, package, provenance, and performance-quality
gates remain required. With no physical attestation, the publisher records
`physical_validation.requirement: optional` and
`physical_validation.status: unverified` in the public release-verification
receipt. It never infers real-phone power behavior or Tesla lamp and actuator
timing from emulator, desktop, or static FSEQ checks.

An optional attestation can be supplied through the protected
LIGHTFORGE_PHYSICAL_VALIDATION_ATTESTATION_JSON environment secret. An unset
or empty secret does not block publication. When supplied, the final
publisher step materializes it only after all setup has completed, writes it to
a private mode-0600 temporary file, immediately unsets the secret, checks the
file is valid JSON, and passes only that file path to the publisher. A shell
cleanup trap removes the file on success, failure, or an interrupt. Neither the
secret nor its path is exported through GITHUB_ENV, printed, uploaded, or added
to a release asset.

The protocol is lightforge-physical-validation-attestation-v1 with Ed25519.
The repository intentionally starts with an empty source-pinned authority
registry. No authority enrollment is needed to publish without physical
evidence. To claim verified physical observations, a reviewed source change
must first add an authority identifier, raw public key, and matching public-key
digest. A secret cannot introduce or replace an authority key. Supplied
evidence must pass every check below; invalid evidence aborts publication
instead of being silently dropped.

## Required binding for supplied evidence

The signed canonical payload is every top-level attestation field except
signed_payload_sha256 and signature_base64. Its digest and the detached
64-byte Ed25519 signature are checked before publication.

| Area | Required binding |
| --- | --- |
| Release | Exact semantic version name and version code. |
| Source | Candidate commit and Git tree SHA. |
| Candidate | Production workflow path, run ID, attempt, evidence session, exact candidate artifact ID/digest, candidate-manifest identity digest, and APK digest. |
| Android evidence | Sealed Android workflow/run/session, Android evidence artifact ID/digest, evidence-manifest digest, and both fresh instrumentation receipt digests. |
| Private raw evidence | A signer-retained raw-evidence manifest SHA-256 and opaque reference. Both are signed; only the manifest digest may appear in the public receipt. |
| Installed APK | Installed APK SHA-256, package, semantic version name, and version code, each equal to the sealed candidate/source release. |
| Physical device | Fingerprint, manufacturer, model, API level, ABI, and the Android package identifier derived from immutable source. |
| Vehicle | Opaque vehicle identity, firmware version, and the literal ID/version plus SHA-256 of web/engine/vehicle-profile.js from the candidate commit. |
| Physical results | All Android pass booleans, Tesla playback and actuator-feasibility booleans, explicit zero safety-incident and uncommanded-event counts, at least 100 global timing samples plus at least 50 class-specific timing samples for each lighting and mechanical class using the source-pinned percentile method, ordered global and per-class p50/p90/p95/p99/max command and perceptual timing errors within the source-pinned limits below, and lighting/mechanical event coverage at or above their source-pinned percentage and eligible-count floors. |
| Review | Opaque reviewer ID, canonical UTC observed/issued/expiry timestamps, pass verdict, observation-to-issue, issue-to-verification, and observation-to-verification ages no greater than 24 hours each, and an expiry no more than 30 days after issue. |

## Source-pinned timing eligibility

The attestation must contain at least **100** global timing samples and at
least **50** timing samples independently for each of the **lighting** and
**mechanical** classes. The global and each class-specific distribution must
use the same source-pinned method and satisfy the same immutable limits; an
external signer cannot weaken them through an attestation secret:

| Metric | P95 maximum | P99 maximum | Maximum maximum |
| --- | ---: | ---: | ---: |
| Command timestamp absolute error | 50 ms | 100 ms | 250 ms |
| Perceptual response absolute error | 250 ms | 500 ms | 1000 ms |

The percentile method is source-pinned as
`linear-interpolation-n-minus-1-v1`: use rank `(N - 1) × p` and linearly
interpolate its neighboring ordered samples. The limits apply after method,
ordering, and finite/non-negative checks. A claim with insufficient global or
class-specific evidence, or any tail value above its limit, is rejected before
release creation.

Lighting coverage must be at least **95%**, and mechanical coverage at least
**90%**, calculated as `realized_events / eligible_events`. Each class must
also contain at least **50 eligible events**. Therefore a percentage-perfect
`1/1` (or `49/49`) class is rejected: these source-pinned floors make
omitted output observable instead of letting it disappear behind a global
aggregate.

## Source-pinned review freshness

Physical observations must be issued within **24 hours**, issuance must be
verified by the publisher within another **24 hours**, and the observation
itself must be no more than **24 hours** old when verification occurs. The
publisher uses its verification clock, not an attestation-supplied clock. All
freshness checks run before signed-payload and signature acceptance, so stale
observations or stale issuance cannot become a valid release claim.

The publisher derives all release, source, candidate, Android-evidence,
package, and vehicle-profile values itself. An attestation with any different
value is rejected before signature verification. The publisher also refuses a
unknown, malformed, expired, non-zero-safety, non-zero-uncommanded,
unordered-percentile, or unverifiable attestation.

Accepted optional evidence records a verified physical result in the public
release receipt without exposing raw device
fingerprints, deterministic device-derived identifiers/hashes, the detached
signature, or the signed-payload digest in public workflow output. The
publisher verifies the payload digest and signature only in memory because that
digest is a deterministic commitment to private device, vehicle, and evidence
reference fields. It does not itself create a physical claim: the external
signer is responsible for retaining the underlying authorized device and
vehicle observations.
