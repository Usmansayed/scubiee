"""Hypothesis: gate/status latency is per-request TCP connect to the stdlib HTTP
server, not handler work. Test by comparing fresh-connection-per-call (current
urllib behavior) vs a persistent keep-alive connection, same /health endpoint."""
from __future__ import annotations
import http.client
import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

HOST, PORT = "127.0.0.1", 8765


def fresh_conn_once():
    c = http.client.HTTPConnection(HOST, PORT, timeout=10)
    c.request("GET", "/health")
    r = c.getresponse(); r.read(); c.close()


def main():
    # 1) fresh connection each call (what urllib does today)
    xs = []
    for _ in range(40):
        t0 = time.perf_counter(); fresh_conn_once(); xs.append((time.perf_counter() - t0) * 1000)
    print("fresh-conn-per-call  /health:", stat(xs))

    # 2) persistent keep-alive connection, reused across calls
    c = http.client.HTTPConnection(HOST, PORT, timeout=10)
    # does the server honor keep-alive? send Connection: keep-alive
    ys = []
    ok_keepalive = True
    for i in range(40):
        try:
            t0 = time.perf_counter()
            c.request("GET", "/health", headers={"Connection": "keep-alive"})
            r = c.getresponse(); r.read()
            ys.append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            ok_keepalive = False
            print(f"  keep-alive dropped at call {i}: {type(e).__name__}: {e}")
            # reconnect to continue measuring
            c.close(); c = http.client.HTTPConnection(HOST, PORT, timeout=10)
    c.close()
    print(f"persistent keep-alive /health: {stat(ys)}  (server_kept_alive={ok_keepalive})")

    # 3) report the HTTP response headers so we know if server advertises keep-alive
    c2 = http.client.HTTPConnection(HOST, PORT, timeout=10)
    c2.request("GET", "/health")
    r2 = c2.getresponse(); r2.read()
    print("response headers:", dict(r2.getheaders()))
    print("http_version:", r2.version, "(10=HTTP/1.0, 11=HTTP/1.1)")
    c2.close()


if __name__ == "__main__":
    main()
