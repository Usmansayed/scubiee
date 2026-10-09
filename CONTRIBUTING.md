# Contributing to Scubiee

Thanks for your interest in improving Scubiee — a local-first code-context engine
and MCP server for AI coding agents. This guide gets you from clone to a verified
change.

## Project layout

Scubiee is a monorepo under `packages/`:

| Package | Role |
|---|---|
| `pipeline` | The product: MCP server, HTTP engine, CLI, lifecycle, indexing, embedder |
| `conductor` | Retrieval fusion — graph + BM25 + dense into one ranked result |
| `graphify` | The code graph — symbols, edges, near-dup detection |
| `trace_lab` | AST tracer + heatmap — the cards `map find`/`focus` return |

Docs live in `docs/` (start at [`docs/README.md`](docs/README.md)); the
user-facing landing-page docs are in `docs/web-info/`. Historical material is
under `docs/archive/`.

## Development setup

Requires **Python 3.10+**. We use [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Usmansayed/scubiee
cd scubiee

# Editable install of the package + its deps
uv pip install -e .

# One-time machine setup (detects GPU: CUDA / DirectML / MLX / CPU)
scubiee setup
```

For in-repo runs (running source directly rather than the installed tool), set
`PYTHONPATH=packages`. For runs against the installed tool, do **not** set it.

## Running tests

```bash
# Full suite
PYTHONPATH=packages python -m pytest tests/ -q

# A focused suite
PYTHONPATH=packages python -m pytest tests/test_reliability_hardening.py -q
```

Some embedding/accelerator tests require a working FastEmbed + ONNX Runtime in
the Python you run tests with; they skip or fail cleanly in an environment
without it. The release/engine Python is the source of truth for embedder
behavior.

## Before you open a PR

1. **Run the certification gate** — this is the single most useful check:
   ```bash
   scubiee certify
   ```
   Expect `ok: true` with `failures: []`.
2. **Run the relevant tests** for the area you touched (and the full suite for
   anything cross-cutting).
3. **Keep changes focused.** One logical change per PR; don't bundle unrelated
   refactors.
4. **Match existing patterns.** Gate risky new behavior behind an environment
   knob with a safe default (see the `CTX_*` conventions in
   [`docs/scubiee-overview.md`](docs/scubiee-overview.md)).
5. **Update docs** if you change a command, flag, or the MCP surface. The
   authoritative tool surface is `packages/pipeline/map_v3_server.py`
   (`map` with `config=find|focus`, plus `gate`/`status`).

## Commit & PR conventions

- Use clear, scoped commit subjects: `fix(keeper): …`, `perf(warm): …`,
  `docs(web-info): …`.
- Describe **what changed and why**, what you tested, and any tradeoffs.
- Never commit secrets, local scratch, build output, or model weights (the
  `.gitignore` covers the common cases).

## Reporting bugs

Open a GitHub issue using the bug template. The most useful attachment is a
diagnostic bundle:

```bash
scubiee diagnose --no-tests --desktop
```

Attach the Desktop JSON plus a tail of `~/.scubiee/engine.log`.

## License

By contributing, you agree that your contributions are licensed under the
project's [Apache License 2.0](LICENSE).
