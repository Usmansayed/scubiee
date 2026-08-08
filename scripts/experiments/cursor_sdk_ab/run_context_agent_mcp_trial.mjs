#!/usr/bin/env node
/**
 * Fast Cursor SDK trial: context-agent MCP gather_context + rule (no Grep).
 *   node run_context_agent_mcp_trial.mjs
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Agent, CursorAgentError } from "@cursor/sdk";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../../..");
const OUT = resolve(ROOT, "out/experiments/cursor_sdk_ab");
const WORK = resolve(
  ROOT,
  "testdata/cursor_sdk_ab/work_d_channel_best_mcponly",
);
const TIMEOUT_MS = Number(process.env.SDK_TRIAL_TIMEOUT_MS || 3 * 60 * 1000);
const QUERY =
  "where is browser lease busy / contention guidance for shared chromium";

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

function installHooks() {
  const rules = join(WORK, ".cursor", "rules");
  const hooks = join(WORK, ".cursor", "hooks");
  mkdirSync(rules, { recursive: true });
  mkdirSync(hooks, { recursive: true });
  writeFileSync(
    join(rules, "context-agent.mdc"),
    `---
description: Use context-agent gather_context first
alwaysApply: true
---
# Context Agent first
1. Call MCP gather_context once for vague locate.
2. Read pack files only, then answer/Edit.
3. Grep/Glob/SemanticSearch are blocked — do not rediscover.
`,
    "utf8",
  );
  writeFileSync(
    join(hooks, "deny-rediscover.cjs"),
    `const fs=require("fs"); let raw=""; try{raw=fs.readFileSync(0,"utf8")}catch{}
let p={}; try{p=JSON.parse(raw||"{}")}catch{}
const t=String(p.tool_name||p.toolName||"");
if(["Grep","Glob","SemanticSearch","SemSearch"].includes(t)){
  process.stdout.write(JSON.stringify({
    permission:"deny",
    agent_message: t+" blocked. Call context-agent gather_context, then Read pack paths."
  }));
  process.exit(0);
}
process.stdout.write(JSON.stringify({permission:"allow"}));
`,
    "utf8",
  );
  writeFileSync(
    join(WORK, ".cursor", "hooks.json"),
    JSON.stringify(
      {
        version: 1,
        hooks: {
          preToolUse: [
            {
              matcher: "Grep|Glob|SemanticSearch",
              command: "node .cursor/hooks/deny-rediscover.cjs",
              failClosed: true,
            },
          ],
        },
      },
      null,
      2,
    ) + "\n",
    "utf8",
  );
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
  if (!run) return { byType: {}, mcpTools: {}, mcpTotal: 0, nativeExplore: 0 };
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
    mcpTotal: byType.mcp || 0,
    nativeExplore: native,
    usage: run.usage,
  };
}

loadEnv();
if (!process.env.CURSOR_API_KEY) throw new Error("CURSOR_API_KEY missing");

const py = venvPython().replace(/\\/g, "/");
const packages = resolve(ROOT, "packages").replace(/\\/g, "/");
const repo = WORK.replace(/\\/g, "/");

// Smoke MCP import (no tokens)
const smoke = spawnSync(
  venvPython(),
  [
    "-c",
    "from pipeline.mcp_context_agent import create_mcp; m=create_mcp(); print(sorted(m._tool_manager._tools.keys()))",
  ],
  {
    cwd: ROOT,
    env: { ...process.env, PYTHONPATH: resolve(ROOT, "packages") },
    encoding: "utf8",
  },
);
console.log("[check] mcp tools", (smoke.stdout || "").trim());
if (smoke.status !== 0) {
  console.error(smoke.stderr);
  process.exit(1);
}

installHooks();

const mcpServers = {
  "context-agent": {
    type: "stdio",
    command: py,
    args: ["-u", "-m", "pipeline.mcp_context_agent"],
    env: {
      PYTHONPATH: packages,
      PYTHONUTF8: "1",
      CTX_REPO: repo,
      CTX_RETRIEVE: "D",
      CTX_ENGINE_URL: "http://127.0.0.1:8765",
      CTX_LLAMA_URL: process.env.CTX_LLAMA_URL || "http://127.0.0.1:8080",
    },
  },
};

const prompt = `LOCATE ONLY — no edits, no pytest.

Use MCP context-agent tool gather_context ONCE with this query, then answer from the pack:
"${QUERY}"

Return exact paths for:
1) shared chromium lease / busy / acquire
2) agent guidance

After gather_context: optional Read of 1–2 pack files, then answer. Grep/Glob are blocked.`;

console.log(`[trial] timeout_min=${TIMEOUT_MS / 60000}`);
const started = Date.now();
let agentId;
let result;
try {
  await using agent = await Agent.create({
    apiKey: process.env.CURSOR_API_KEY,
    name: `ctx-agent-mcp-${Date.now()}`,
    model: { id: "composer-2.5" },
    local: { cwd: WORK, settingSources: ["project"] },
    mcpServers,
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
const text = result.result || "";
const usedGather = Object.keys(stats.mcpTools || {}).some((k) =>
  /gather_context/i.test(k),
);
const report = {
  trial: "context-agent MCP + rule",
  status: result.status,
  timed_out: Boolean(result.timed_out),
  elapsed_ms: Date.now() - started,
  agentId,
  usage: stats.usage || result.usage,
  tool_mix: stats.byType,
  mcpTools: stats.mcpTools,
  used_gather_context: usedGather,
  nativeExplore: stats.nativeExplore,
  pass_hint:
    usedGather &&
    (/shared_lease|browser_session_manager|agent_guidance/.test(text) ||
      result.status === "finished"),
  result_preview: text.slice(0, 1200),
};

mkdirSync(OUT, { recursive: true });
const outPath = join(OUT, "trial_context_agent_mcp.json");
writeFileSync(outPath, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
console.log(`[trial] wrote ${outPath}`);
process.exit(report.pass_hint ? 0 : 2);
