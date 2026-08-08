#!/usr/bin/env node
/**
 * Cursor SDK A/B: Graphify vs D_channel_best — real usage.totalTokens.
 *
 * Usage:
 *   node run_ab.mjs --check          # auth + folders + MCP smoke (no agent tokens)
 *   node run_ab.mjs --arm graphify    # run one arm
 *   node run_ab.mjs --arm d_channel_best
 *   node run_ab.mjs --all            # sequential both arms
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Agent, Cursor, CursorAgentError } from "@cursor/sdk";
import { installForArm } from "./install_mcp_prefer.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../../..");
/** Results / reports (ok under gitignored out/) */
const OUT = resolve(ROOT, "out/experiments/cursor_sdk_ab");
/**
 * Work copies live under testdata/ — NOT out/ — because parent .gitignore
 * ignores /out/, and graphify collect_files then indexes 0 files.
 */
const WORK_BASE = resolve(ROOT, "testdata/cursor_sdk_ab");
const MISSION = JSON.parse(
  readFileSync(resolve(__dirname, "mission.json"), "utf8"),
);

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
    ) {
      v = v.slice(1, -1);
    }
    const key = m[1];
    if (!(key in process.env) || !process.env[key]) process.env[key] = v;
  }
  if (!process.env.CURSOR_API_KEY && process.env.cursor_api_key) {
    process.env.CURSOR_API_KEY = process.env.cursor_api_key;
  }
}

function venvPython() {
  const win = resolve(ROOT, ".venv/Scripts/python.exe");
  return existsSync(win) ? win : "python";
}

function armPaths(arm) {
  const work =
    arm === "graphify"
      ? resolve(WORK_BASE, "work_graphify_mcponly")
      : resolve(WORK_BASE, "work_d_channel_best_mcponly");
  return { work };
}

function projectId(work) {
  const idFile = join(work, ".context-engine", "id.json");
  if (!existsSync(idFile)) return null;
  return JSON.parse(readFileSync(idFile, "utf8")).project_id;
}

function graphJson(work) {
  const pid = projectId(work);
  if (!pid) return null;
  const g = join(
    process.env.USERPROFILE || process.env.HOME,
    ".context-engine",
    "projects",
    pid,
    "graph.json",
  );
  return existsSync(g) ? g : null;
}

function mcpForArm(arm, work) {
  const py = venvPython().replace(/\\/g, "/");
  const packages = resolve(ROOT, "packages").replace(/\\/g, "/");
  const repo = work.replace(/\\/g, "/");

  if (arm === "graphify") {
    const graph = graphJson(work);
    if (!graph) {
      throw new Error(
        `graph.json missing for ${work} — index that folder first`,
      );
    }
    const gServe = {
      type: "stdio",
      command: py,
      args: ["-u", "-m", "graphify.serve", graph.replace(/\\/g, "/")],
      env: { PYTHONPATH: packages, PYTHONUTF8: "1" },
    };
    return {
      // Override ambient user "context-engine" so it cannot leak fat tools.
      "context-engine": gServe,
      graphify: gServe,
    };
  }

  const leanCe = {
    type: "stdio",
    command: py,
    // Yesterday-style: D_rerank search_code only; agent Reads hit files natively.
    args: ["-u", "-m", "pipeline.mcp_d_rerank_only"],
    env: {
      PYTHONPATH: packages,
      PYTHONUTF8: "1",
      CTX_REPO: repo,
      CTX_RETRIEVE: "D",
      CTX_ENGINE_URL: "http://127.0.0.1:8765",
    },
  };

  return {
    "context-engine": leanCe,
    "ce-d-rerank": leanCe,
  };
}

function systemHint(arm) {
  if (arm === "graphify") {
    return (
      "Index is warm — do NOT reindex. Stay in this workspace. " +
      "Built-in Read/Grep/Glob are BLOCKED. " +
      "Use graphify MCP: query_graph, then get_node / get_neighbors. " +
      "Then Edit + Shell(pytest≤2)."
    );
  }
  return (
    "Index is warm — do NOT reindex. Stay in this workspace. " +
    "Workflow (yesterday-style):\n" +
    "1) context-engine search_code FIRST (1–2 calls) for vague NL → top related chunks.\n" +
    "2) Native Read on those hit files (Read/Grep allowed).\n" +
    "3) Edit + Shell(pytest≤2). Do not spam search_code."
  );
}

const ARM_TIMEOUT_MS = Number(process.env.SDK_AB_TIMEOUT_MS || 12 * 60 * 1000);

async function waitWithTimeout(run, ms, label) {
  let timer;
  try {
    return await Promise.race([
      run.wait(),
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          reject(new Error(`TIMEOUT ${label} after ${Math.round(ms / 60000)}m`));
        }, ms);
      }),
    ]);
  } catch (err) {
    try {
      await run.cancel();
      console.error(`[${label}] cancelled after error/timeout:`, err.message);
    } catch (cancelErr) {
      console.error(`[${label}] cancel failed:`, cancelErr.message);
    }
    // best-effort final state
    try {
      const late = await run.wait();
      return { ...late, timed_out: true, timeout_error: String(err.message || err) };
    } catch {
      return {
        status: "cancelled",
        timed_out: true,
        timeout_error: String(err.message || err),
        usage: run.usage,
        id: run.id,
      };
    }
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function warmEngine(work, retrieveMode) {
  const py = venvPython();
  // Soft warm only — force_restart caused long stalls / hung A/B runs.
  const script = `
from pathlib import Path
import os
os.environ["CTX_RETRIEVE"] = ${JSON.stringify(retrieveMode)}
from pipeline.daemon import ensure_daemon
from pipeline.client import EngineClient
repo = Path(${JSON.stringify(work)})
info = ensure_daemon(repo)
c = EngineClient()
opened = c.open_repo(str(repo), wait=True)
st = c.status(str(repo))
eng = st.get("engine") or {}
print({"ensure": info.get("ok", True), "open": opened.get("ok"), "warm": st.get("warm_state"), "chunks": eng.get("chunks"), "root": eng.get("root")})
`;
  const r = spawnSync(py, ["-c", script], {
    cwd: ROOT,
    env: {
      ...process.env,
      PYTHONPATH: resolve(ROOT, "packages"),
      CTX_RETRIEVE: retrieveMode,
      PYTHONUTF8: "1",
    },
    encoding: "utf8",
  });
  if (r.stdout) process.stdout.write(r.stdout);
  if (r.stderr) process.stderr.write(r.stderr.slice(-2000));
  if (r.status !== 0) throw new Error(`warmEngine failed status=${r.status}`);
}

async function checkSetup() {
  loadEnv();
  const key = process.env.CURSOR_API_KEY;
  if (!key || key.length < 20) {
    throw new Error("CURSOR_API_KEY missing/too short in .env");
  }
  console.log(`[check] CURSOR_API_KEY len=${key.length}`);

  const me = await Cursor.me({ apiKey: key });
  console.log(
    `[check] Cursor.me ok name=${me.apiKeyName || "?"} email=${me.userEmail || "?"}`,
  );

  for (const arm of MISSION.arms) {
    const { work } = armPaths(arm);
    if (!existsSync(work)) throw new Error(`missing work folder ${work}`);
    const pid = projectId(work);
    if (!pid) throw new Error(`${arm}: not indexed (no .context-engine/id.json)`);
    const g = graphJson(work);
    if (!g) throw new Error(`${arm}: graph.json missing under projects/${pid}`);
    console.log(`[check] ${arm} work ok project_id=${pid}`);
  }

  // Smoke CE search without agent tokens
  const ceWork = armPaths("d_channel_best").work;
  warmEngine(ceWork, "D");
  const py = venvPython();
  const smoke = spawnSync(
    py,
    [
      "-c",
      `
from pipeline.client import EngineClient
c = EngineClient()
out = c.search("browser session contention lease guidance", top_k=5, path=r"""${ceWork}""")
hits = out.get("hits") or []
print({"ok": out.get("ok", True), "n": len(hits), "top": [(h.get("file") or h.get("path"), h.get("source")) for h in hits[:3]]})
`,
    ],
    {
      cwd: ROOT,
      env: {
        ...process.env,
        PYTHONPATH: resolve(ROOT, "packages"),
        CTX_RETRIEVE: "D",
        CTX_ENGINE_URL: "http://127.0.0.1:8765",
      },
      encoding: "utf8",
    },
  );
  console.log("[check] CE search smoke:", (smoke.stdout || "").trim());
  if (smoke.status !== 0) {
    console.error(smoke.stderr);
    throw new Error("CE search smoke failed");
  }

  // Yesterday-style D_rerank-only MCP
  const modSmoke = spawnSync(
    py,
    ["-c", "from pipeline.mcp_d_rerank_only import create_mcp; m=create_mcp(); print('mcp_ok', m.name, sorted(m._tool_manager._tools))"],
    {
      cwd: ROOT,
      env: {
        ...process.env,
        PYTHONPATH: resolve(ROOT, "packages"),
        CTX_RETRIEVE: "D",
      },
      encoding: "utf8",
    },
  );
  console.log("[check] d_rerank_only MCP:", (modSmoke.stdout || "").trim());
  if (modSmoke.status !== 0) {
    console.error(modSmoke.stderr);
    throw new Error("mcp_d_rerank_only import failed");
  }

  // Graphify smoke
  const gWork = armPaths("graphify").work;
  const gPath = graphJson(gWork);
  const gSmoke = spawnSync(
    py,
    [
      resolve(ROOT, "scripts/experiments/cursor_ab/graphify_cli.py"),
      "query_graph",
      "browser session lease guidance",
      "--graph",
      gPath,
      "--budget",
      "800",
    ],
    {
      cwd: ROOT,
      env: { ...process.env, PYTHONPATH: resolve(ROOT, "packages") },
      encoding: "utf8",
    },
  );
  const gOut = (gSmoke.stdout || "").slice(0, 400);
  console.log("[check] graphify smoke chars=", gOut.length, "preview=", gOut.slice(0, 120).replace(/\n/g, " "));
  if (gSmoke.status !== 0 || gOut.length < 20) {
    throw new Error("graphify smoke failed");
  }

  console.log("[check] SETUP_OK — safe to run agents");
}

async function auditTools(agentId, cwd) {
  const runs = await Agent.listRuns(agentId, { runtime: "local", cwd });
  const run = runs.items[0];
  if (!run) return { byType: {}, mcpTools: {}, nativeExplore: 0, mcpTotal: 0 };
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
  return {
    byType,
    mcpTools,
    nativeExplore: native,
    mcpTotal: byType.mcp || 0,
    mcpOnlyExplore: native === 0 && (byType.mcp || 0) > 0,
  };
}

async function runArm(arm) {
  loadEnv();
  const key = process.env.CURSOR_API_KEY;
  if (!key) throw new Error("CURSOR_API_KEY missing");
  const { work } = armPaths(arm);
  const retrieve = arm === "d_channel_best" ? "D" : "R_plan";
  if (arm === "d_channel_best") {
    warmEngine(work, "D");
  }

  installForArm(work, arm);
  const mcpServers = mcpForArm(arm, work);
  const prompt = `${systemHint(arm)}\n\n${MISSION.prompt}`;

  console.log(`[${arm}] starting cwd=${work}`);
  console.log(`[${arm}] mcp=${Object.keys(mcpServers).join(",")}`);
  console.log(`[${arm}] mode=${arm === "graphify" ? "graphify_force" : "d_rerank_read"}`);

  const started = Date.now();
  let result;
  try {
    await using agent = await Agent.create({
      apiKey: key,
      name: `sdk-ab-mcponly-${arm}-${Date.now()}`,
      model: { id: MISSION.model || "composer-2.5" },
      local: {
        cwd: work,
        // Load .cursor/rules + hooks (CE: Read allowed; graphify: Read denied)
        settingSources: ["project"],
      },
      mcpServers,
    });
    console.log(`[${arm}] agentId=${agent.agentId}`);
    console.log(`[${arm}] timeout_min=${(ARM_TIMEOUT_MS / 60000).toFixed(1)}`);
    const run = await agent.send(prompt);
    result = await waitWithTimeout(run, ARM_TIMEOUT_MS, arm);
    result = {
      ...result,
      agentId: agent.agentId,
      runId: run.id,
      usage: result.usage || run.usage,
    };
  } catch (err) {
    if (err instanceof CursorAgentError) {
      console.error(`[${arm}] startup failed:`, err.message);
      throw err;
    }
    throw err;
  }

  const elapsedMs = Date.now() - started;
  const usage = result.usage || {};
  const toolAudit = await auditTools(result.agentId, work);
  const record = {
    arm,
    status: result.status,
    agentId: result.agentId,
    runId: result.runId,
    elapsed_ms: elapsedMs,
    model: result.model,
    usage: {
      inputTokens: usage.inputTokens ?? null,
      outputTokens: usage.outputTokens ?? null,
      cacheReadTokens: usage.cacheReadTokens ?? null,
      cacheWriteTokens: usage.cacheWriteTokens ?? null,
      totalTokens: usage.totalTokens ?? null,
      reasoningTokens: usage.reasoningTokens ?? null,
    },
    tool_audit: toolAudit,
    result_preview: (result.result || "").slice(0, 1500),
    error: result.error || null,
    finished_at: new Date().toISOString(),
  };

  mkdirSync(OUT, { recursive: true });
  const outPath = join(OUT, `result_${arm}.json`);
  writeFileSync(outPath, JSON.stringify(record, null, 2));
  console.log(`[${arm}] wrote ${outPath}`);
  console.log(
    `[${arm}] status=${record.status} totalTokens=${record.usage.totalTokens} elapsed_min=${(elapsedMs / 60000).toFixed(1)} mcp=${toolAudit.mcpTotal} nativeExplore=${toolAudit.nativeExplore}`,
  );
  return record;
}

function summarize() {
  const arms = [];
  for (const arm of MISSION.arms) {
    const p = join(OUT, `result_${arm}.json`);
    if (existsSync(p)) arms.push(JSON.parse(readFileSync(p, "utf8")));
  }
  if (arms.length < 2) {
    console.log("[summary] need both results");
    return;
  }
  const byTok = [...arms].sort(
    (a, b) => (a.usage.totalTokens ?? 1e15) - (b.usage.totalTokens ?? 1e15),
  );
  const report = {
    mission: MISSION.title,
    metric: MISSION.metric,
    prompt: MISSION.prompt,
    arms,
    verdict: {
      token_winner: byTok[0]?.arm,
      tokens: Object.fromEntries(
        arms.map((a) => [a.arm, a.usage.totalTokens]),
      ),
    },
  };
  writeFileSync(join(OUT, "report_latest.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report.verdict, null, 2));
}

const args = process.argv.slice(2);
const mode = args.includes("--check")
  ? "check"
  : args.includes("--all")
    ? "all"
    : args.includes("--summarize")
      ? "summarize"
      : "arm";
const armFlag = args.includes("--arm")
  ? args[args.indexOf("--arm") + 1]
  : null;

if (mode === "check") {
  checkSetup().catch((e) => {
    console.error(e);
    process.exit(1);
  });
} else if (mode === "summarize") {
  summarize();
} else if (mode === "all") {
  (async () => {
    await checkSetup();
    await runArm("graphify");
    await runArm("d_channel_best");
    summarize();
  })().catch((e) => {
    console.error(e);
    process.exit(1);
  });
} else if (armFlag) {
  runArm(armFlag)
    .then(() => summarize())
    .catch((e) => {
      console.error(e);
      process.exit(1);
    });
} else {
  console.log(
    "Usage: node run_ab.mjs --check | --all | --arm graphify|d_channel_best | --summarize",
  );
  process.exit(2);
}
