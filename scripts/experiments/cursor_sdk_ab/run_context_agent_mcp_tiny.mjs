#!/usr/bin/env node
/**
 * Tiny trial: ONE gather_context → answer from pack. No Read/Grep.
 *   node run_context_agent_mcp_tiny.mjs
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Agent } from "@cursor/sdk";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../../..");
const OUT = resolve(ROOT, "out/experiments/cursor_sdk_ab");
const WORK = resolve(
  ROOT,
  "testdata/cursor_sdk_ab/work_d_channel_best_mcponly",
);
const TIMEOUT_MS = Number(process.env.SDK_TRIAL_TIMEOUT_MS || 90_000);
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
  const hooks = join(WORK, ".cursor", "hooks");
  const rules = join(WORK, ".cursor", "rules");
  mkdirSync(hooks, { recursive: true });
  mkdirSync(rules, { recursive: true });
  writeFileSync(
    join(rules, "context-agent.mdc"),
    `---
description: One gather_context then answer
alwaysApply: true
---
# Tiny pack trial
Call gather_context once. Then answer from the pack JSON. No Read/Grep/Glob.
`,
    "utf8",
  );
  writeFileSync(
    join(hooks, "deny-explore.cjs"),
    `const fs=require("fs"); let raw=""; try{raw=fs.readFileSync(0,"utf8")}catch{}
let p={}; try{p=JSON.parse(raw||"{}")}catch{}
const t=String(p.tool_name||p.toolName||"");
if(["Grep","Glob","Read","SemanticSearch","SemSearch"].includes(t)){
  process.stdout.write(JSON.stringify({
    permission:"deny",
    agent_message: t+" blocked. Answer from gather_context pack only."
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
              matcher: "Grep|Glob|Read|SemanticSearch",
              command: "node .cursor/hooks/deny-explore.cjs",
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
          () => reject(new Error(`TIMEOUT ${Math.round(ms / 1000)}s`)),
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
      return {
        ...late,
        timed_out: true,
        timeout_error: String(err.message || err),
      };
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
  if (!run) return { byType: {}, mcpTools: {} };
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
  return { byType, mcpTools, usage: run.usage };
}

loadEnv();
if (!process.env.CURSOR_API_KEY) throw new Error("CURSOR_API_KEY missing");

installHooks();

const py = venvPython().replace(/\\/g, "/");
const packages = resolve(ROOT, "packages").replace(/\\/g, "/");
const repo = WORK.replace(/\\/g, "/");

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

const prompt = `TINY LOCATE — no edits.

1) Call MCP gather_context ONCE with: "${QUERY}"
2) Immediately answer from that pack JSON only. Do NOT Read/Grep/Glob. Do NOT call gather_context again.

Reply with exact paths:
- lease/busy/acquire:
- agent guidance:`;

console.log(`[tiny] timeout_s=${TIMEOUT_MS / 1000}`);
const started = Date.now();
await using agent = await Agent.create({
  apiKey: process.env.CURSOR_API_KEY,
  name: `ctx-agent-tiny-${Date.now()}`,
  model: { id: "composer-2.5" },
  local: { cwd: WORK, settingSources: ["project"] },
  mcpServers,
});
const agentId = agent.agentId;
console.log(`[tiny] agentId=${agentId}`);
const run = await agent.send(prompt);
const result = await waitWithTimeout(run, TIMEOUT_MS);
const stats = await audit(agentId);
const text = result.result || "";
const gatherN = stats.mcpTools?.["context-agent:gather_context"] || 0;
const pathsOk =
  /shared_lease|browser_session_manager/i.test(text) &&
  /agent_guidance/i.test(text);
const report = {
  trial: "context-agent MCP tiny (1 pack → answer)",
  status: result.status,
  timed_out: Boolean(result.timed_out),
  elapsed_ms: Date.now() - started,
  agentId,
  usage: stats.usage || result.usage,
  tool_mix: stats.byType,
  mcpTools: stats.mcpTools,
  gather_calls: gatherN,
  used_gather_once: gatherN === 1,
  paths_ok: pathsOk,
  pass: gatherN >= 1 && pathsOk && !result.timed_out,
  result_preview: text.slice(0, 800),
};

mkdirSync(OUT, { recursive: true });
const outPath = join(OUT, "trial_context_agent_mcp_tiny.json");
writeFileSync(outPath, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
console.log(`[tiny] wrote ${outPath}`);
process.exit(report.pass ? 0 : 2);
