# Scubiee Website Content — quick reference

> **Version:** [0.3.14](https://pypi.org/project/scubiee/0.3.14/) (published on PyPI)  
> **Purpose:** Short snippets, taglines, and SEO for marketing pages.  
> **Full product bible (use this to write the website):** **[`product-guide-for-website.md`](./product-guide-for-website.md)**  
> **Operator docs:** [`../docs/web-info/`](../docs/web-info/README.md)

---

## Start here for website writing

| Writing task | Read |
|--------------|------|
| **Full product story, features, pages, FAQ** | **[Product guide for website](./product-guide-for-website.md)** |
| Command tables & setup flows | [Commands and setup](./commands-and-setup.md) |
| Engineering / architecture depth | [Context engine internals](./context-engine-internals.md) |
| End-user troubleshooting | [docs/web-info](../docs/web-info/README.md) |

---

## Tagline options

- "Local code search that actually understands your repository."
- "Give every AI coding tool semantic search. Locally."
- "Index once, search from anywhere. No cloud required."
- "The missing context layer for AI coding assistants."
- "Your codebase, indexed once — ready for every AI tool."

## One-liner

Scubiee is a local code context engine that gives AI coding tools semantic search, graph-aware retrieval, and live re-indexing — without uploading your code anywhere.

## Hero subhead (2 lines)

Index your repository on your machine. Connect Cursor, Copilot, Claude Code, or Kiro via MCP.  
Agents find code by meaning — not random grepping — and stay current as you ship.

---

## Key features (feature grid — expand in product guide)

| Feature | One sentence |
|---------|--------------|
| Semantic search | Find code by meaning with CodeRankEmbed + FAISS |
| Graph-aware | Follow imports, callers, and structure |
| Live sync | Merkle incremental re-index after edits |
| MCP-native | map · focus · grep · glob · workspace tools |
| Multi-tool connect | One `scubiee connect` family for 12+ AI tools |
| GPU-aware | CUDA · DirectML · MLX · CPU auto-detected |
| Fully local | No code upload; model download only at setup |
| Safe lifecycle | Confirm-gated wipe; honest audit on full uninstall |

Details: [product-guide-for-website.md § Features in depth](./product-guide-for-website.md#features-in-depth)

---

## How it works (homepage diagram)

```
1. SETUP                 2. INDEX               3. CONNECT
scubiee setup --repair    scubiee init .         scubiee connect --cursor
     |                    |                      |
     v                    v                      v
Detect GPU/CPU/MLX   Parse + embed code     Write MCP + agent rules
Download model       Store vectors/graph    Reload IDE MCP
```

**Critical copy rule:** `init` indexes · `connect` wires the IDE · reload MCP.

---

## Architecture (simplified)

```
AI Tool (Cursor / Copilot / …)
        | MCP
        v
Scubiee MCP  →  Local Engine (daemon)  →  Vectors + Graph + Chunks
                      ↑
               ~/.scubiee + <repo>/.scubiee
```

---

## Install block (website code panel)

```bash
uv tool install --force scubiee==0.3.14 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
cd your-repo && scubiee init .
scubiee connect --cursor    # reload MCP in IDE
```

Windows Access denied → `scubiee unlock-tool` then retry.

---

## MCP tools (marketing table)

| Tool | Hook for website |
|------|------------------|
| `map` | "Where is X handled?" — ranked code map |
| `focus` | Deep-dive spans, neighbors, call sites |
| `grep` | Exact literals when you know the string |
| `gate` / `status` | One check: is this repo ready? |

Full reference: [mcp-tools-reference.md](../docs/web-info/mcp-tools-reference.md)

---

## Comparison one-liners

- **vs grep alone:** meaning + structure + freshness  
- **vs cloud index:** private, air-gapped, your disk  
- **vs DIY RAG:** minutes not weeks; MCP included  

---

## SEO keywords

scubiee, local code search, semantic code search, MCP server, AI coding tools, code context engine, repository indexing, cursor mcp, copilot mcp, claude code mcp, directml, mlx, offline code ai

---

## Social proof bullets

- CPU-only Windows laptop: setup completes without DirectML hang  
- Security review: code never uploaded for search  
- Monorepo: agent finds the right module on first `map`  
- Multi-IDE: same local index for Cursor and Copilot  

More stories: [product guide § Social proof](./product-guide-for-website.md#social-proof--use-case-stories)
