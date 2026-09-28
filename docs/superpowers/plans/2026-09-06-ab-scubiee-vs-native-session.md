# A/B trial 2: Scubiee vs native (session isolation)

**Task:** How does Scubiee keep two parallel Cursor chats from sharing locate state (packed ids, pins, session store)?

**Agents:** [Scubiee](b871df79-9c9e-4bd5-8c74-ff7976b20262) vs [Native](e1ac2351-341e-4123-9da0-0ba04e292201)

## Efficiency

| | Scubiee (map→pack→expand→spans) | Native (Grep/Read only) |
|---|---|---|
| tool_calls | 13 (~10 investigative) | 20 |
| chars ingested | **~28,000** | **~38,000** |
| ratio | **1.0×** | **~1.36×** more tokens |
| answer quality | aligned | aligned (+ more docs/tests) |

## Shared verdict (both correct)

- State buckets under `.scubiee/sessions/<sid>/` (`session_store.json` + `work_session.json`).
- `resolve_session` / `effective_session_id`: explicit → request → transport (`cursor@chat-*` / `@conn-*`) → env → process id.
- Fail-closed = `CTX_MCP_SESSION_ISOLATE=1` refuses legacy shared `default` store (not a `require_session_id` hard-error API).
- Shared MCP process risk if two chats get the same transport/process id with no explicit session.

## vs trial 1 (connect write path)

| Trial | Scubiee chars | Native chars | Scubiee advantage |
|---|---|---|---|
| 1 connect | ~46k | ~92k | ~2.0× |
| 2 session | ~28k | ~38k | ~1.36× |

Scubiee won both on tokens; margin smaller when native Grep hits the right modules early (session_isolation is a sharp keyword).
