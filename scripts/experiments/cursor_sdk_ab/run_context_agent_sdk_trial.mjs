#!/usr/bin/env node
/**
 * Small Cursor SDK trial: Context Agent (Qwen) pack → main agent locate-only.
 *
 *   node run_context_agent_sdk_trial.mjs
 *
 * Does NOT run a full feature A/B. Locate only, short timeout.
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
const TIMEOUT_MS = Number(process.env.SDK_TRIAL_TIMEOUT_MS || 5 * 60 * 1000);
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

function gatherPack() {
  const py = venvPython();
  const packPath = join(OUT, "sdk_trial_context_pack.json");
  mkdirSync(OUT, { recursive: true });
  const r = spawnSync(
    py,
    [
      "-m",
      "pipeline.context_agent",
      QUERY,
      "--repo",
      WORK,
      "--rounds",
      "4",
      "--out",
      packPath,
    ],
    {
      cwd: ROOT,
      env: {
        ...process.env,
        PYTHONPATH: resolve(ROOT, "packages"),
        PYTHONUTF8: "1",
        CTX_REPO: WORK,
        CTX_RETRIEVE: "D",
        CTX_LLAMA_URL: process.env.CTX_LLAMA_URL || "http://127.0.0.1:8080",
      },
      encoding: "utf8",
      timeout: 180000,
    },
  );
  if (r.stdout) process.stdout.write(r.stdout.slice(-1500));
  if (r.status !== 0) {
    console.error(r.stderr?.slice(-2000));
    throw new Error(`context_agent failed status=${r.status}`);
  }
  return JSON.parse(readFileSync(packPath, "utf8"));
}

function slimPackForPrompt(pack) {
  return {
    summary: pack.summary,
    files: (pack.files || []).slice(0, 8),
    notes: pack.notes || [],
    hits: (pack.snippets || [])
      .filter((s) => s.kind === "search_hit")
      .slice(0, 6)
      .map((s) => ({
        file: s.file,
        start_line: s.start_line,
        end_line: s.end_line,
        why: (s.why || "").slice(0, 120),
      })),
    tool_trace: pack.tool_trace || [],
  };
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
  if (!run) return { byType: {}, mcpTotal: 0, nativeExplore: 0 };
  const turns = await run.conversation();
  const byType = {};
  for (const t of turns) {
    if (t.type !== "agentConversationTurn") continue;
    for (const s of t.turn.steps || []) {
      if (s.type !== "toolCall") continue;
      const typ = (s.message || {}).type || "unknown";
      byType[typ] = (byType[typ] || 0) + 1;
    }
  }
  const native =
    (byType.grep || 0) +
    (byType.glob || 0) +
    (byType.read || 0) +
    (byType.semanticSearch || 0);
  return {
    byType,
    mcpTotal: byType.mcp || 0,
    nativeExplore: native,
    usage: run.usage,
  };
}

loadEnv();
if (!process.env.CURSOR_API_KEY) throw new Error("CURSOR_API_KEY missing");

console.log("[trial] gathering Context Agent pack (Qwen+CE)…");
let pack;
const reuse = join(OUT, "sdk_trial_context_pack.json");
if (process.env.REUSE_PACK === "1" && existsSync(reuse)) {
  pack = JSON.parse(readFileSync(reuse, "utf8"));
  console.log("[trial] reusing existing pack");
} else {
  pack = gatherPack();
}
if (!pack.ok) throw new Error(`pack not ok: ${pack.error || "unknown"}`);
const slim = slimPackForPrompt(pack);
console.log(
  `[trial] pack files=${(slim.files || []).length} steps=${pack.steps} summary=${(slim.summary || "").slice(0, 120)}`,
);

const prompt = `LOCATE ONLY — do NOT edit, do NOT pytest, do NOT Grep/Glob the whole repo.

A Context Agent already found the answer. USE THIS PACK — do not rediscover.

CONTEXT_PACK:
${JSON.stringify(slim, null, 2)}

Answer in under 10 lines with exact paths:
1) shared chromium lease / busy / acquire → from pack (expect shared_lease.py and/or browser_session_manager.py)
2) agent guidance → from pack (expect agent_guidance.py if listed)

You may Read at most TWO pack files for confirmation. Then answer immediately.`;

// Soft project rule: discourage rediscovery
const rulesDir = join(WORK, ".cursor", "rules");
mkdirSync(rulesDir, { recursive: true });
writeFileSync(
  join(rulesDir, "pack-first.mdc"),
  `---
description: Prefer CONTEXT_PACK over Grep/Glob rediscovery
alwaysApply: true
---
If the user message includes CONTEXT_PACK, answer from it. Do not Grep/Glob the tree. At most 2 Reads of pack paths.
`,
  "utf8",
);

const hooksDir = join(WORK, ".cursor", "hooks");
mkdirSync(hooksDir, { recursive: true });
writeFileSync(
  join(hooksDir, "deny-explore.cjs"),
  `const fs=require("fs"); let raw=""; try{raw=fs.readFileSync(0,"utf8")}catch{}
let p={}; try{p=JSON.parse(raw||"{}")}catch{}
const tool=String(p.tool_name||p.toolName||"");
if(["Grep","Glob","SemanticSearch","SemSearch"].includes(tool)){
  process.stdout.write(JSON.stringify({permission:"deny",agent_message:tool+" blocked — use CONTEXT_PACK / Read pack paths only"}));
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

console.log(`[trial] Cursor SDK locate (timeout ${TIMEOUT_MS / 60000}m)…`);
const started = Date.now();
let agentId;
let result;
try {
  await using agent = await Agent.create({
    apiKey: process.env.CURSOR_API_KEY,
    name: `ctx-agent-sdk-trial-${Date.now()}`,
    model: { id: "composer-2.5" },
    local: { cwd: WORK, settingSources: ["project"] },
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
  trial: "context_agent_pack → Cursor SDK locate",
  status: result.status,
  timed_out: Boolean(result.timed_out),
  elapsed_ms: Date.now() - started,
  agentId,
  pack: {
    steps: pack.steps,
    files: slim.files,
    summary: slim.summary,
    tool_trace: slim.tool_trace,
  },
  usage: stats.usage || result.usage,
  tool_mix: stats.byType,
  mcpTotal: stats.mcpTotal,
  nativeExplore: stats.nativeExplore,
  result_preview: (result.result || "").slice(0, 1500),
  pass_hint:
    (result.result || "").includes("shared_lease") ||
    (result.result || "").includes("browser_session_manager") ||
    (result.result || "").includes("agent_guidance"),
};

mkdirSync(OUT, { recursive: true });
const outPath = join(OUT, "trial_context_agent_sdk.json");
writeFileSync(outPath, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
console.log(`[trial] wrote ${outPath}`);
process.exit(report.pass_hint || report.status === "finished" ? 0 : 2);
