# scubiee

One command. Installs the Python Context Engine, picks CUDA / DirectML / CoreML / CPU, registers Cursor MCP.

```bash
npm install -g scubiee
```

Requires **Python 3.10+** on PATH. Then `ctx init <repo>` for each codebase.

Skip machine setup during npm install: `CTX_SKIP_SETUP=1 npm install -g scubiee` then run `ctx setup`.
