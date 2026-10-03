"""Tight test: does the keepalive keep FOCUS fast after idle? Drives the source
map_v3_server worker. Per arm: spawn, idle 70s, then fire focus 3x (report min=steady,
and the FIRST which is the real after-idle number). Compare control vs keepalive."""
from __future__ import annotations
import json, os, subprocess, time
from pathlib import Path

REPO = r"C:\Users\usman\Downloads\context-engine"
PY = r"C:\Users\usman\Miniconda3\python.exe"
IDLE_S = 70
ARGS = {"config":"focus","names":["choose_strategy"]}


def env(interval):
    e = dict(os.environ)
    e["PYTHONPATH"] = str(Path(REPO)/"packages"); e["PYTHONIOENCODING"]="utf-8"
    e["CTX_ENGINE_URL"]="http://127.0.0.1:8765"; e["CTX_REPO"]=REPO
    e["CTX_PROJECT_ID"]="ce_3536ac8e8e83bb8e4d888db37847729c"
    e["CTX_MAP_WARM_INTERVAL_S"]=str(interval)
    for k in ("MINI_ENGINE_URL","MINI_REPO","MINI_PROJECT_ID"): e.pop(k,None)
    return e


class W:
    def __init__(self, interval):
        self.p=subprocess.Popen([PY,"-u","-m","pipeline.map_v3_server"],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding="utf-8",env=env(interval),cwd=REPO)
        self._id=0
    def rpc(self,m,p=None):
        self._id+=1
        self.p.stdin.write(json.dumps({"jsonrpc":"2.0","id":self._id,"method":m,"params":p or {}})+"\n")
        self.p.stdin.flush(); return json.loads(self.p.stdout.readline())
    def notify(self,m): self.p.stdin.write(json.dumps({"jsonrpc":"2.0","method":m})+"\n"); self.p.stdin.flush()
    def call(self,n,a):
        r=self.rpc("tools/call",{"name":n,"arguments":a})
        return r.get("result",{}).get("content",[{}])[0].get("text","")
    def close(self):
        try: self.p.stdin.close(); self.p.terminate()
        except Exception: pass


def arm(label, interval):
    w=W(interval); w.rpc("initialize"); w.notify("notifications/initialized"); time.sleep(2.0)
    time.sleep(IDLE_S)
    xs=[]
    for i in range(3):
        t=time.perf_counter(); txt=w.call("map",ARGS); xs.append(round((time.perf_counter()-t)*1000,1))
    w.close()
    print(f"  {label:10s} interval={interval:>3}  first_after_idle={xs[0]:8.1f}ms  calls={xs}  out={len(txt)}c", flush=True)
    return {"interval": interval, "first_after_idle_ms": xs[0], "calls_ms": xs, "chars": len(txt)}


def main():
    print(f"idle={IDLE_S}s, focus x3 per arm", flush=True)
    res={"control": arm("CONTROL",0), "keepalive_default": arm("KEEPALIVE",120)}
    Path(REPO,"dist","_keepalive_focus.json").write_text(json.dumps(res,indent=2),encoding="utf-8")
    print("WROTE dist/_keepalive_focus.json")


if __name__ == "__main__":
    main()
