"""STARTUP — is the ~393ms first-_http tax the Windows proxy-registry probe?
Fresh process A: first call via default urlopen (current). Fresh process B: first call
via an opener built with an EMPTY ProxyHandler (no getproxies registry read).
Each run is a SEPARATE python process so 'first call' is truly cold. Prints both."""
from __future__ import annotations
import json, os, sys, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, ENGINE, PY, base_env  # noqa: E402

MODE = sys.argv[1] if len(sys.argv) > 1 else "default"
URL = ENGINE + "/health"


def main():
    if MODE == "noproxy":
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        t0 = time.perf_counter()
        with opener.open(URL, timeout=8) as r:
            r.read()
        dt = (time.perf_counter() - t0) * 1000
    else:
        t0 = time.perf_counter()
        with urllib.request.urlopen(URL, timeout=8) as r:
            r.read()
        dt = (time.perf_counter() - t0) * 1000
    print(json.dumps({"mode": MODE, "first_http_ms": round(dt, 1)}))


if __name__ == "__main__":
    main()
