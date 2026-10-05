# Release process

Release artifacts contain the portable application and its dependencies. Source
control contains code, documentation, example settings, and build instructions.
Recordings, actual settings, logs, caches, local environments, and downloaded
models do not belong in a commit.

## Prepare a release

1. Update `pyproject.toml`, `src/whistle_dictation/__init__.py`, and `CHANGELOG.md`
   to the same version. Record validation and known limitations accurately.
2. Install pinned development dependencies with `Setup.ps1` on Windows AMD64.
3. Run lint and unit tests, native doctor, offscreen smoke, and relevant acceptance
   checks. Synthetic speech checks are available through `scripts/VerifySpeech.ps1`.
4. Build with `scripts/Build.ps1`. Keep the complete one-folder output together.
5. Run the packaged smoke and doctor, then assemble the ZIP with
   `scripts/PackageRelease.ps1`. Packaging excludes mutable `data/` and generates
   `SHA256SUMS.txt` alongside the ZIP.

## Publish

Commit the reviewed source and documentation on `main`, wait for CI, and create
an annotated `v<version>` tag. Publish a GitHub release from that tag with the
portable ZIP and checksum file as assets. Use the corresponding changelog entry
as the basis for release notes, including the early-release status and remaining
manual desktop validation.

Repository: https://github.com/smafnan/whistle-dictation

Do not overwrite an existing version's assets or move a published tag to different
source. Correct a published release with a new version. Tag creation, pushes,
and release publication are explicit maintainer actions; the CI workflow does
not automatically publish releases.

## Licenses and integrity

The bundle must include the project MIT license, upstream dependency license
resources, the model/runtime license, and the runtime manifest. Verify all local
native artifacts before assembly. Upstream revisions and SHA256 pins are in
`src/whistle_dictation/runtime.py` and `docs/runtime-findings.md`.

The project does not currently provide reproducible byte-for-byte executable
builds, code signing, or a Windows installer. Dependency and model pins support
repeatable setup; build-tool metadata can still change the executable hash.
