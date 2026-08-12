# Context Engine — Engineering Documentation

Start here. Read the documents below in order.

## What is this?

Context Engine is a local code search daemon for AI coding agents. It indexes a repository into embeddings + a structural code graph, serves semantic search over HTTP, and exposes tools to agents via MCP (Model Context Protocol). The goal: agents find the right code with fewer tokens than blind grep.

## Documents

| # | Document | What it covers |
|---|----------|---------------|
| 1 | [Architecture](./01-architecture.md) | System overview, process model, data flow, how everything connects |
| 2 | [Indexing and Embeddings](./02-indexing-and-embeddings.md) | How code enters the system: parsing, chunking, enrichment, compression, embedding, vector storage |
| 3 | [Retrieval and Search](./03-retrieval-and-search.md) | How queries are answered: conductor fusion, freshness, hot-patching, capability cards |
| 4 | [Agent Tools and MCP](./04-agent-tools-and-mcp.md) | What the agent sees: MCP surfaces, tool parameters, session store, instructions |
| 5 | [Background Systems](./05-background-systems.md) | Daemon, watchdog, keeper sync loop, resource manager, hardware acceleration |
| 6 | [Research and Experiments](./06-research-and-experiments.md) | A/B testing infrastructure, retrieval quality benchmarks, experiment results |

## Quick orientation

```
packages/pipeline/     — Core engine (indexing, search, daemon, MCP, CLI)
packages/graphify/     — Tree-sitter AST extraction + NetworkX graph
packages/conductor/    — Triple-signal retrieval (graph + BM25 + dense)
packages/enrich/       — Chunk slicing + metadata injection
packages/repo_ir/      — Structural intermediate representation (the data contract)
packages/metadata/     — Graph-derived chunk headers
packages/seir/         — Experimental embedding text representations
packages/hybrid_cbm/   — CE + Codebase Memory hybrid MCP facade
packages/parse_harness/ — Graphify-to-RepoIR adapter
scripts/               — Benchmarks and A/B experiment harnesses
testdata/frontend-mcp/ — Test repository for experiments
```

## Entry points

- `ctx` CLI → `pipeline.__main__:main` (index, search, serve, engine start/stop, setup)
- `ctx-mcp` → `pipeline.mcp_server:main` → `pipeline.mcp_locate:main` (MCP stdio server)
- HTTP daemon → `pipeline.server:run_server` on `127.0.0.1:8765`

## First things to do

1. Read the Architecture doc to understand how the pieces fit together.
2. Run `ctx setup` on a repo to see the system work end-to-end.
3. Look at `packages/pipeline/engine.py` — that's the hot path for search.
