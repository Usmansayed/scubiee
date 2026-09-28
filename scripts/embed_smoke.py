from pathlib import Path

from pipeline.embedder import Embedder

cache = Path("fixtures/trace-lab/.embed_cache/coderank.jsonl")
cache.parent.mkdir(parents=True, exist_ok=True)
e = Embedder(cache_path=cache, quiet=True, batch_size=8)
docs = [
    "def authenticate(request): return JwtService().verify(token)",
    "def charge(user_id, cents): return get('/pay')",
    "TOKEN_TTL = 3600",
]
V = e.embed_many(docs, is_query=False)
q = e.embed_one("how do users get logged in", is_query=True)
print("dim", V.shape, "cos", [float(q @ V[i]) for i in range(3)])
e.flush_cache()
print("ok", cache.stat().st_size)
