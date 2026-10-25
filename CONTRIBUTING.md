# Contributing to Scubiee

Thanks for your interest in improving Scubiee, a local-first code-context engine and MCP server
for AI coding agents. Scubiee is maintained mainly by one person, and contributions of every size
are welcome: bug fixes, docs, tests, and focused improvements.

Please follow the [code of conduct](CODE_OF_CONDUCT.md) in all project spaces.

## Before you start

- **Search first.** Check [existing issues](https://github.com/Usmansayed/scubiee/issues) and
  [pull requests](https://github.com/Usmansayed/scubiee/pulls) to avoid duplicate work.
- **Small changes can go straight to a PR**: typo and doc fixes, clear bug fixes, missing tests.
- **Discuss bigger changes first.** For new features, changes to the MCP tool surface, or
  architectural changes (indexing, sync, retrieval, storage), open an issue describing the idea
  before writing a lot of code. It saves you from building something that can't be merged.

## Reporting bugs

Open an issue with the **Bug report** form and include:

- A clear description of the problem.
- Steps to reproduce it.
- What you expected and what actually happened.
- Your Scubiee version (`scubiee --version`), OS, accelerator (CUDA / DirectML / MLX / CPU), and
  the IDE or MCP client you use.
- Sanitized logs or screenshots. The most useful attachment is a diagnostic bundle:

  ```bash
  scubiee diagnose --no-tests --desktop
  ```

  plus the relevant tail of `~/.scubiee/engine.log`.

Remove secrets, tokens, and private source code from anything you paste.

**Security vulnerabilities must not be reported in public issues.** Follow
[SECURITY.md](SECURITY.md) instead.

## Requesting features

Open an issue with the **Feature request** form and explain:

- The problem or use case.
- The solution you propose.
- Alternatives you considered, if any.
- Who benefits and how.

## Development setup

Requirements: **Python 3.11+**, [Git](https://git-scm.com/), and [uv](https://docs.astral.sh/uv/)
(recommended; plain `pip` + `venv` also works).

1. Fork the repository on GitHub, then clone your fork:

   ```bash
   git clone https://github.com/<your-username>/scubiee
   cd scubiee
   ```

2. Create a virtual environment and install Scubiee in editable mode, plus pytest:

   ```bash
   uv venv
   # macOS / Linux
   source .venv/bin/activate
   # Windows (PowerShell)
   .venv\Scripts\Activate.ps1

   uv pip install -e . pytest
   ```

3. Run the one-time machine setup. It detects your accelerator and downloads the embedding model
   (~270 MB). This is the only network step Scubiee needs:

   ```bash
   scubiee setup
   ```

4. Try your build on a repository:

   ```bash
   scubiee init .
   scubiee search "where is the sync loop" .
   ```

The code lives under `packages/`:

| Package | Role |
|---|---|
| `pipeline` | The product: CLI, MCP server, local HTTP engine, indexing, sync, embedder |
| `conductor` | Retrieval fusion: graph + BM25 + dense into one ranked result |
| `graphify` | The code graph: symbols, edges, near-duplicate detection (bundled; see [NOTICE](NOTICE)) |
| `trace_lab` | AST tracer and heatmap behind the cards `map find` / `focus` return |

The authoritative MCP tool surface is `packages/pipeline/map_v3_server.py` (`map` with
`config=find|focus`, plus `gate` / `status`). Docs live in [`docs/`](docs/README.md); user-facing
guides are in [`docs/web-info/`](docs/web-info/README.md).

## Running tests and checks

```bash
# Full suite (takes a while)
python -m pytest tests -q

# A focused file while you iterate
python -m pytest tests/test_reliability_hardening.py -q
```

If you run tests against the source tree without an editable install, set `PYTHONPATH=packages`.
Some embedding and accelerator tests need a working FastEmbed + ONNX Runtime in the Python you test
with; they skip or fail cleanly without it.

Before opening a PR, also run the certification gate:

```bash
scubiee certify
```

Expect `ok: true` with `failures: []`.

## Branches and pull requests

Work on a focused branch with a descriptive name:

- `fix/describe-the-bug`
- `feat/describe-the-feature`
- `docs/describe-the-change`

A good pull request:

- Has a clear purpose and a description of **what changed and why**.
- Stays focused and reasonably small (one logical change per PR).
- Includes tests when it changes behavior or fixes a bug.
- Updates docs when a command, flag, or the MCP surface changes.
- Calls out breaking changes.
- Avoids unrelated formatting or refactoring.
- Contains no secrets, credentials, local scratch files, build output, or model weights.

Commit subjects follow a scoped style, for example `fix(keeper): …`, `perf(warm): …`,
`docs(web-info): …`.

The maintainer may ask for changes, defer a proposal, or decline a PR that doesn't fit the
project's direction. That is never a judgment of you. Thank you for contributing either way.

## Code quality

- Follow the conventions of the code around your change.
- Don't add dependencies unless they're clearly needed; discuss new ones in the issue first.
- Keep existing behavior working. Gate risky new behavior behind an environment variable with a
  safe default (see the `CTX_*` conventions in [`docs/scubiee-overview.md`](docs/scubiee-overview.md)).
- Scubiee runs on Windows, macOS, and Linux, so avoid platform-specific assumptions where you can.

## Releases

Releases are cut by the maintainer: the version in `pyproject.toml` and `npm/package.json` is
bumped, the package is published to PyPI, and notable changes are recorded in
[CHANGELOG.md](CHANGELOG.md). Contributors don't need to bump versions.

## License

Scubiee is licensed under the [Apache License 2.0](LICENSE). By submitting a contribution, you
agree that it is provided under the terms of that license (see section 5 of the license). You keep
the copyright to your contribution; no separate contributor agreement is required.
