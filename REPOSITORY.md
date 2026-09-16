# Repository maintenance

Keep one maintained source tree, one current build guide and explicit evidence
boundaries. [README.md](README.md) is the user entry point;
[docs/README.md](docs/README.md) indexes focused guides and contracts.
[version.json](version.json) owns source version metadata, while
[GitHub Releases](https://github.com/CyberBASSLord-666/LightForge/releases) owns
published APK availability. Do not copy changing release-status paragraphs into
multiple documents.

## What belongs in Git

Retain application code, canonical required assets, pinned converters and
manifests, dependency lockfiles, test fixtures, versioned evidence referenced by
verification, third-party notices and reviewed release requests. `qa/` is not
simply a disposable output folder: current tests reuse historical harnesses and
some numerical protocols require immutable receipts.

Do not commit build/SDK caches, npm or Python environments, private signing
material, personal music/diagnostics, generated large activation dumps, or split
copies of assets already available at canonical paths. Generated GAME/Deux
graphs are reproduced by the pinned build tools rather than checked in.

Use GitHub release assets for published APKs. Preserve their original signer,
checksums and public verification records. Repository visibility is public;
private projects, audio and credentials do not belong here. Visibility does not
change the third-party rights described in [ASSETS.md](ASSETS.md).

## Layout

| Path | Purpose |
| --- | --- |
| `android/`, `web/` | Shipped application and canonical runtime assets |
| `tools/`, `tests/` | Build, verification, release tooling and automated contracts |
| `docs/` | Focused maintained documentation |
| `qa/` | Current release harnesses, required references and historical evidence |
| `research/` | Model/geometry source, attribution and retained research inputs; not an APK payload |
| `releases/` | Historical requests, public signing deltas, publication metadata and release pointers |
| `.github/workflows/` | Maintained verification/publication and focused diagnostic workflows |

## Check a change

Run from the repository root after staging additions/removals, so the index
represents the intended checkout:

```bash
python3 tools/repository_hygiene.py
python3 tests/test_repository_hygiene.py
python3 tools/sync_version.py --check
git diff --check
```

The hygiene checker validates maintained Markdown links, documents the boundary
of its checks, and rejects retired transfer paths, build caches and common
credential filenames. It uses tracked paths, so a sparse checkout is supported.
It does not scan arbitrary secret contents or validate every external URL;
manual review and the existing release security controls remain necessary.
Application, model or verification changes must also pass their applicable
[build/test gates](BUILD.md). A fast hygiene check is not a substitute for them.

Before removing a file, inspect code, workflow, manifest and documentation
references. Do not delete versioned tests by age, alter golden hashes, relax
release checks, remove licenses or reduce model quality to obtain a smaller tree.
Check open PRs before touching shared runtime files.

## Retired transfer material and historical recovery

The completed 1.6 import formerly kept split copies of eight restored source
assets and a published APK. Those transfer pieces and their one-time restoration
utilities are no longer needed in a working checkout. The canonical source
assets remain, and the original APK is available through the
[1.6.0 release record](releases/v1.6.0/README.md).

The old snapshot manifest, migration scripts, import-era documentation and
one-shot 2.2.1 artifact-recovery workflows are recoverable from Git history.
The last pre-cleanup main source is
`07511f5544b688c657773dce8a29d8d31ba68cb1`. Inspect that revision in a separate
worktree when researching the import; do not run its snapshot validator against
current application sources or promote historical records to current proof.

This cleanup is an ordinary forward commit. It does not rewrite history,
force-push, alter published tags/assets or change another PR. Removing duplicate
files reduces the current checkout and future shallow clones; it does not purge
those bytes from existing clones or GitHub's historical object database.

For a fresh current-source checkout:

```bash
git clone --depth 1 --single-branch https://github.com/CyberBASSLord-666/LightForge.git
```

Fetch older history explicitly when needed. History rewriting and shared-branch
cleanup are separate, coordinated operations—not an implicit part of routine
source maintenance.

## Keep documentation accurate

Use relative links to canonical guides instead of repeated procedures. Keep
release history in [CHANGELOG.md](CHANGELOG.md) and evidence pointers in
[VALIDATION.md](VALIDATION.md). Label unmeasured performance, optional inputs and
physical observations honestly. Update implementation contracts alongside code;
do not erase unfinished capability work to make a readiness document look green.
