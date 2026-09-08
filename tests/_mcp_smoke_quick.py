import json, os, subprocess, queue, threading, time
from pathlib import Path

repo = Path(r"C:\Users\usman\Downloads\context-engine")
mcp = Path(r"C:\Users\usman\AppData\Roaming\uv\tools\scubiee\Scripts\scubiee-mcp.exe")
env = os.environ.copy()
env.update(
    {
        "CTX_REPO": str(repo),
        "CTX_PROJECT_ID": "ce_223fe983ee19e5629ce88102e6581038",
        "CTX_ENGINE_URL": "http://127.0.0.1:8765",
        "PYTHONUTF8": "1",
    }
)
cf = 0x08000000 if os.name == "nt" else 0
p = subprocess.Popen(
    [str(mcp)],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
    env=env,
    creationflags=cf,
)


def send(o):
    p.stdin.write(json.dumps(o) + "\n")
    p.stdin.flush()


def recv(t=60):
    q = queue.Queue()
    threading.Thread(target=lambda: q.put(p.stdout.readline()), daemon=True).start()
    deadline = time.time() + t
    while time.time() < deadline:
        if not q.empty():
            return q.get()
        time.sleep(0.05)
    return ""


send(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "1"},
        },
    }
)
recv()
send({"jsonrpc": "2.0", "method": "notifications/initialized"})
time.sleep(1.0)
rid = 1

for name, args in [
    ("status", {}),
    ("map", {"query": "lifecycle guard global stop init blocked"}),
    ("grep", {"pattern": "def connect", "glob": "packages/pipeline/*.py", "max_hits": 3}),
]:
    rid += 1
    send({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": args}})
    line = recv(90)
    data = json.loads(line) if line.strip() else {}
    if data.get("id") != rid:
        # drain one more line if log noise interleaved
        line2 = recv(10)
        if line2.strip():
            data = json.loads(line2)
    text = data.get("result", {}).get("content", [{}])[0].get("text", "")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        obj = {"raw": text[:200]}
    err = obj.get("error", "")
    count = int(obj.get("count") or len(obj.get("cards") or obj.get("hits") or []))
    ok = obj.get("ok", True) is not False and not err
    if name == "map":
        ok = ok and count > 0
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] mcp:{name} error={err!r} count={count}")

p.terminate()
