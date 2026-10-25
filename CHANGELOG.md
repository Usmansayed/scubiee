# Changelog

All notable changes to Scubiee are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Scubiee uses version numbers of the
form `0.MINOR.PATCH` while in beta.

Releases are published to [PyPI](https://pypi.org/project/scubiee/#history). Versions before
0.3.165 are not listed here; see the [Git tags](https://github.com/Usmansayed/scubiee/tags) and
the PyPI release history.

## [Unreleased]

### Added

- Open-source project docs: code of conduct, support guide, changelog, NOTICE, and GitHub issue
  forms.
- Token-savings benchmarks for Claude Code and Kiro in `benchmarks/`.

## [0.3.174] - 2026-10-25

### Fixed

- `faiss.index` no longer doubles in size after a full rebuild or compaction; a mismatched index
  is rebuilt from the compressed vectors on load.
- The embedding cache is kept as one compact array, its append log is truncated after each
  snapshot, and entries for deleted code are pruned.
- Vectors whose chunk context drifted (for example after imports changed) are detected and
  re-embedded during sync, a capped number per sync.

## [0.3.173] - 2026-10-20

### Fixed

- `scubiee upgrade` reports when a release is not yet on the package index instead of showing a
  Windows file-lock hint.

## [0.3.172] - 2026-10-20

### Fixed

- `scubiee upgrade` uses a single PyPI check to decide both "already latest" and the target
  version.

## [0.3.171] - 2026-10-20

### Fixed

- `scubiee upgrade` pins the target version and refreshes the index, so a just-published release
  actually installs.

## [0.3.170] - 2026-10-20

### Fixed

- Prune marking keeps absolute paths out of the repository on macOS and Linux.
- An engine on a non-default port (`CTX_ENGINE_URL`) no longer trusts the running engine's pid.
- `map` shows the engine's refusal reason instead of `HTTP Error 409: Conflict`.

## [0.3.169] - 2026-10-20

### Changed

- `scubiee upgrade` always refreshes MCP configuration and agent rules for the new version.

## [0.3.168] - 2026-10-20

### Fixed

- Built-in ignore rules are hardened so dependency trees and git-ignored files never reach the
  index.

## [0.3.167] - 2026-10-20

### Fixed

- The first `map find` after a worker (re)start no longer takes about 3 seconds.

## [0.3.166] - 2026-10-20

### Fixed

- `scubiee wipe --all --keep-package` no longer deletes the tool on Windows.

## [0.3.165] - 2026-10-20

### Fixed

- CLI engine port handling, `map` auto-starting the engine, and a false `doctor` alarm during an
  in-progress sync.

[Unreleased]: https://github.com/Usmansayed/scubiee/compare/5b91493...HEAD
[0.3.174]: https://pypi.org/project/scubiee/0.3.174/
[0.3.173]: https://pypi.org/project/scubiee/0.3.173/
[0.3.172]: https://pypi.org/project/scubiee/0.3.172/
[0.3.171]: https://pypi.org/project/scubiee/0.3.171/
[0.3.170]: https://pypi.org/project/scubiee/0.3.170/
[0.3.169]: https://pypi.org/project/scubiee/0.3.169/
[0.3.168]: https://pypi.org/project/scubiee/0.3.168/
[0.3.167]: https://pypi.org/project/scubiee/0.3.167/
[0.3.166]: https://pypi.org/project/scubiee/0.3.166/
[0.3.165]: https://pypi.org/project/scubiee/0.3.165/
