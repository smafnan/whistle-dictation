# Security policy

## Supported versions

Security fixes target the latest 0.x release. Earlier development builds should
be updated before reporting a problem that has already been corrected.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/smafnan/whistle-dictation/security/advisories/new)
when enabled. Do not put credentials, private speech recordings, or sensitive
transcripts into a public issue. If private reporting is unavailable, open an issue
requesting a private reporting channel without including exploit details.

Include the affected version, reproduction steps using synthetic data, impact,
and a proposed mitigation if available. Response times are not guaranteed for
this independently maintained project.

## Current boundaries

- The app runs as the current Windows user and does not require elevation.
- Setup explicitly downloads pinned public model/runtime artifacts; startup
  checks their SHA256 hashes before loading native code.
- Audio and the latest transcript are held in memory during normal use; settings
  and metadata-only logs remain in the app directory.
- The worker is isolated in a process for crash and cancellation handling. This
  is not a security sandbox for untrusted native code.
- Focus checks use native Windows handles and process identity. They cannot
  distinguish every browser/Electron field sharing a handle or make text
  delivery atomic.
- The portable executable is currently unsigned.

Compatibility limitations and manual checks are documented in
[ACCEPTANCE.md](docs/ACCEPTANCE.md).
