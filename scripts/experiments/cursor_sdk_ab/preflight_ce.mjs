#!/usr/bin/env node
/**
 * Preflight before spending agent tokens on CE MCP-only arm.
 * Exit 0 only if all checks pass.
 */
import { readFileSync, existsSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../../..");
const OUT = resolve(ROOT, "out/experiments/cursor_sdk_ab");
const WORK = resolve(ROOT, "testdata/cursor_sdk_ab/work_d_channel_best_mcponly");

function loadEnv() {
  const envPath = resolve(ROOT, ".env");
  for (const line of readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!m) continue;
    let v = m[2].trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'")))
      v = v.slice(1, -1);
    if (!process.env[m[1]]) process.env[m[1]] = v;
  }
  if (!process.env.CURSOR_API_KEY && process.env.cursor_api_key)
    process.env.CURSOR_API_KEY = process.env.cursor_api_key;
}

function py() {
  const win = resolve(ROOT, ".venv/Scripts/python.exe");
  return existsSync(win) ? win : "python";
}

const checks = [];
function ok(name, pass, detail) {
  checks.push({ name, pass: !!pass, detail });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? " — " + detail : ""}`);
}

loadEnv();

ok("CURSOR_API_KEY", !!(process.env.CURSOR_API_KEY && process.env.CURSOR_API_KEY.length > 20), `len=${(process.env.CURSOR_API_KEY||"").length}`);
ok("work_folder", existsSync(WORK), WORK);
ok("hooks.json", existsSync(join(WORK, ".cursor/hooks.json")));
ok("prefer-mcp.cjs", existsSync(join(WORK, ".cursor/hooks/prefer-mcp.cjs")));
ok("project id", existsSync(join(WORK, ".context-engine/id.json")));

const hook = spawnSync("node", [join(WORK, ".cursor/hooks/prefer-mcp.cjs")], {
  input: JSON.stringify({ tool_name: "Grep" }),
  encoding: "utf8",
});
let denied = false;
try {
  denied = JSON.parse(hook.stdout || "{}").permission === "deny";
} catch {}
ok("hook_denies_Grep", denied, (hook.stdout || "").slice(0, 80));

const clean = spawnSync(
  py(),
  [
    "-c",
    `
from pathlib import Path
w=Path(r'''${WORK.replace(/\\/g, "\\\\")}''')
hits=[]
for p in w.rglob('*.py'):
  t=p.read_text(encoding='utf-8', errors='ignore')
  if 'BrowserBusy' in t or 'browser_busy' in t or 'def contention_hint' in t:
    hits.append(str(p.relative_to(w)))
print(len(hits))
`,
  ],
  { encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1" } },
);
ok("workspace_clean", (clean.stdout || "").trim() === "0", `markers=${(clean.stdout||"").trim()}`);

const bench = spawnSync(
  py(),
  [
    "-c",
    `
import time
from pathlib import Path
from pipeline.client import EngineClient
from pipeline.daemon import ensure_daemon
repo=Path(r'''${WORK.replace(/\\/g, "\\\\")}''')
ensure_daemon(repo)
c=EngineClient()
c.open_repo(str(repo), wait=True)
times={}
for name,fn in [
 ('search', lambda: c.search('browser session lease', top_k=5, path=str(repo))),
 ('grep_ident', lambda: c.grep_ident('acquire', keep=2, max_chars=300, path=str(repo))),
 ('grep', lambda: c.grep('busy|lease', glob='*.py', max_hits=8, path=str(repo))),
 ('query_graph', lambda: c.query_graph('browser lease', keep=3, max_chars=250, repo=str(repo))),
]:
  t0=time.perf_counter(); out=fn(); times[name]=round(time.perf_counter()-t0,2)
print(times)
assert times['search'] < 15 and times['grep'] < 5 and times['query_graph'] < 5
`,
  ],
  {
    cwd: ROOT,
    encoding: "utf8",
    env: {
      ...process.env,
      PYTHONPATH: resolve(ROOT, "packages"),
      CTX_RETRIEVE: "D_channel_best",
      CTX_ENGINE_URL: "http://127.0.0.1:8765",
      PYTHONUTF8: "1",
    },
  },
);
ok(
  "ce_tools_fast",
  bench.status === 0,
  ((bench.stdout || "") + (bench.stderr || "")).trim().slice(-200),
);

ok(
  "graphify_result_saved",
  existsSync(join(OUT, "result_graphify_mcponly.json")) ||
    existsSync(join(OUT, "result_graphify.json")),
);

const failed = checks.filter((c) => !c.pass);
writeFileSync(
  join(OUT, "preflight_ce_mcponly.json"),
  JSON.stringify({ ok: failed.length === 0, checks }, null, 2),
);
console.log(failed.length === 0 ? "\nPREFLIGHT_OK" : "\nPREFLIGHT_FAIL");
process.exit(failed.length === 0 ? 0 : 2);
