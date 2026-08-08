#!/usr/bin/env node
/**
 * Small soft-prefer sim: locate-only, encourage CE MCP (no deny hooks, no full feature A/B).
 *
 *   node run_mcp_prefer_trial.mjs
 *
 * PASS soft: at least one context-engine MCP call (d_rerank / query_graph / …).
 * Native Read/Grep allowed — encouraged, not forced.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Agent, CursorAgentError } from "@cursor/sdk";
import { installMcpPrefer } from "./install_mcp_prefer.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../../..");
const OUT = resolve(ROOT, "out/experiments/cursor_sdk_ab");
const WORK = resolve(ROOT, "testdata/cursor_sdk_ab/work_d_channel_best_mcponly");
const TIMEOUT_MS = Number(process.env.SDK_TRIAL_TIMEOUT_MS || 6 * 60 * 1000);

function loadEnv() {
  const envPath = resolve(ROOT, ".env");
  if (!existsSync(envPath)) return;
  for (const line of readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!m) continue;
    let v = m[2].trim();
    if (
      (v.startsWith('"') && v.endsWith('"')) ||
      (v.startsWith("'") && v.endsWith("'"))
    )
      v = v.slice(1, -1);
    if (!process.env[m[1]]) process.env[m[1]] = v;
  }
  if (!process.env.CURSOR_API_KEY && process.env.cursor_api_key) {
    process.env.CURSOR_API_KEY = process.env.cursor_api_key;
  }
}

function venvPython() {
  const win = resolve(ROOT, ".venv/Scripts/python.exe");
  return existsSync(win) ? win : "python";
}

function warmEngine() {
  const py = venvPython();
  const script = `
from pathlib import Path
import os
os.environ["CTX_RETRIEVE"] = "D"
from pipeline.daemon import ensure_daemon
from pipeline.client import EngineClient
repo = Path(r"""${WORK.replace(/\\/g, "\\\\")}""")
print(ensure_daemon(repo, force_if_hung=False))
c = EngineClient()
print(c.open_repo(str(repo), wait=True).get("ok"), c.status(str(repo)).get("warm_state"))
`;
  const r = spawnSync(py, ["-c", script], {
    cwd: ROOT,
    env: {
      ...process.env,
      PYTHONPATH: resolve(ROOT, "packages"),
      CTX_RETRIEVE: "D",
      PYTHONUTF8: "1",
    },
    encoding: "utf8",
  });
  if (r.stdout) process.stdout.write(r.stdout);
  if (r.status !== 0) {
    console.error(r.stderr?.slice(-1500));
    throw new Error("warm failed");
  }
}

async function waitWithTimeout(run, ms) {
  let timer;
  try {
    return await Promise.race([
      run.wait(),
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error(`TIMEOUT after ${Math.round(ms / 60000)}m`)),
          ms,
        );
      }),
    ]);
  } catch (err) {
    try {
      await run.cancel();
    } catch {
      /* ignore */
    }
    try {
      const late = await run.wait();
      return { ...late, timed_out: true, timeout_error: String(err.message || err) };
    } catch {
      return {
        status: "cancelled",
        timed_out: true,
        timeout_error: String(err.message || err),
        usage: run.usage,
      };
    }
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function audit(agentId) {
  const runs = await Agent.listRuns(agentId, { runtime: "local", cwd: WORK });
  const run = runs.items[0];
  const turns = await run.conversation();
  const byType = {};
  const mcpTools = {};
  for (const t of turns) {
    if (t.type !== "agentConversationTurn") continue;
    for (const s of t.turn.steps || []) {
      if (s.type !== "toolCall") continue;
      const msg = s.message || {};
      const typ = msg.type || "unknown";
      byType[typ] = (byType[typ] || 0) + 1;
      if (typ === "mcp") {
        const k = `${msg.args?.providerIdentifier || "?"}:${msg.args?.toolName || "?"}`;
        mcpTools[k] = (mcpTools[k] || 0) + 1;
      }
    }
  }
  const native =
    (byType.grep || 0) +
    (byType.glob || 0) +
    (byType.read || 0) +
    (byType.semanticSearch || 0);
  const mcp = byType.mcp || 0;
  const ceKeys = Object.keys(mcpTools).filter(
    (k) =>
      /context-engine|ce-d-rerank|d_rerank|query_graph|get_node|get_neighbors/i.test(
        k,
      ),
  );
  const usedCe = ceKeys.some((k) => (mcpTools[k] || 0) > 0);
  return {
    usage: run.usage,
    byType,
    mcpTools,
    nativeExplore: native,
    mcpTotal: mcp,
    usedCe,
    softOk: usedCe,
  };
}

loadEnv();
if (!process.env.CURSOR_API_KEY) throw new Error("CURSOR_API_KEY missing");
if (!existsSync(WORK)) throw new Error(`missing work ${WORK}`);

console.log("[trial] soft prefer (encourage, no deny hooks)");
installMcpPrefer(WORK);
warmEngine();

const py = venvPython().replace(/\\/g, "/");
const packages = resolve(ROOT, "packages").replace(/\\/g, "/");
const repo = WORK.replace(/\\/g, "/");

const leanCe = {
  type: "stdio",
  command: py,
  args: ["-u", "-m", "pipeline.mcp_d_rerank_graph"],
  env: {
    PYTHONPATH: packages,
    PYTHONUTF8: "1",
    CTX_REPO: repo,
    CTX_RETRIEVE: "D",
    CTX_ENGINE_URL: "http://127.0.0.1:8765",
  },
};

const prompt = `SMALL SIM (locate only — do NOT edit files, do NOT run pytest).

Find where shared Chromium lease / busy / contention guidance should live.
Return exact repo-relative paths for:
1) browser session lease / acquire manager
2) agent guidance for degraded/errors

Prefer context-engine MCP first: d_rerank → query_graph → get_node/get_neighbors.
Native Read/Grep are allowed if needed. Stay in this folder. Be brief.`;

console.log(`[trial] timeout_min=${(TIMEOUT_MS / 60000).toFixed(1)}`);
const started = Date.now();

let agentId;
let result;
try {
  await using agent = await Agent.create({
    apiKey: process.env.CURSOR_API_KEY,
    name: `ce-soft-trial-${Date.now()}`,
    model: { id: "composer-2.5" },
    local: {
      cwd: WORK,
      settingSources: ["project"],
    },
    mcpServers: {
      "context-engine": leanCe,
      "ce-d-rerank-graph": leanCe,
    },
  });
  agentId = agent.agentId;
  console.log(`[trial] agentId=${agentId}`);
  const run = await agent.send(prompt);
  result = await waitWithTimeout(run, TIMEOUT_MS);
  result = { ...result, usage: result.usage || run.usage, agentId };
} catch (err) {
  if (err instanceof CursorAgentError) {
    console.error("[trial] startup failed", err.message);
    process.exit(1);
  }
  throw err;
}

const stats = await audit(agentId);
const report = {
  trial: "soft-prefer CE MCP (encourage, locate-only)",
  status: result.status,
  timed_out: Boolean(result.timed_out),
  elapsed_ms: Date.now() - started,
  agentId,
  usage: stats.usage || result.usage,
  tool_mix: stats.byType,
  mcpTools: stats.mcpTools,
  nativeExplore: stats.nativeExplore,
  mcpTotal: stats.mcpTotal,
  usedCe: stats.usedCe,
  verdict: stats.softOk
    ? "PASS — used Context Engine MCP at least once (native allowed)"
    : "FAIL — Context Engine MCP unused",
  result_preview: (result.result || "").slice(0, 1200),
};

mkdirSync(OUT, { recursive: true });
const outPath = join(OUT, "trial_soft_prefer.json");
writeFileSync(outPath, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
console.log(`[trial] wrote ${outPath}`);
process.exit(stats.softOk ? 0 : 2);
