#!/usr/bin/env node
/** Ultra-tiny: answer from precomputed pack only (no MCP, no Read). */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Agent } from "@cursor/sdk";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../../..");
const OUT = resolve(ROOT, "out/experiments/cursor_sdk_ab");
const WORK = resolve(ROOT, "testdata/cursor_sdk_ab/work_d_channel_best_mcponly");
const TIMEOUT_MS = Number(process.env.SDK_TRIAL_TIMEOUT_MS || 60_000);

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

loadEnv();
const pack = JSON.parse(
  readFileSync(join(OUT, "sdk_trial_context_pack_tiny.json"), "utf8"),
);

mkdirSync(join(WORK, ".cursor", "hooks"), { recursive: true });
writeFileSync(
  join(WORK, ".cursor", "hooks", "deny-all-explore.cjs"),
  `const fs=require("fs"); let raw=""; try{raw=fs.readFileSync(0,"utf8")}catch{}
let p={}; try{p=JSON.parse(raw||"{}")}catch{}
const t=String(p.tool_name||p.toolName||"");
if(["Grep","Glob","Read","SemanticSearch","SemSearch"].includes(t)){
  process.stdout.write(JSON.stringify({permission:"deny",agent_message:t+" blocked — answer from CONTEXT_PACK only"}));
  process.exit(0);
}
process.stdout.write(JSON.stringify({permission:"allow"}));
`,
);
writeFileSync(
  join(WORK, ".cursor", "hooks.json"),
  JSON.stringify({
    version: 1,
    hooks: {
      preToolUse: [
        {
          matcher: "Grep|Glob|Read|SemanticSearch",
          command: "node .cursor/hooks/deny-all-explore.cjs",
          failClosed: true,
        },
      ],
    },
  }) + "\n",
);

const prompt = `ANSWER NOW. Do not call any tools.

CONTEXT_PACK:
${JSON.stringify(pack, null, 2)}

Exact paths only:
1) lease/busy/acquire:
2) agent guidance:`;

const t0 = Date.now();
await using agent = await Agent.create({
  apiKey: process.env.CURSOR_API_KEY,
  name: `ctx-pack-answer-tiny-${Date.now()}`,
  model: { id: "composer-2.5" },
  local: { cwd: WORK, settingSources: ["project"] },
});
console.log(`[answer] agentId=${agent.agentId} timeout_s=${TIMEOUT_MS / 1000}`);
const run = await agent.send(prompt);
let result;
try {
  result = await Promise.race([
    run.wait(),
    new Promise((_, rej) =>
      setTimeout(() => rej(new Error(`TIMEOUT ${TIMEOUT_MS / 1000}s`)), TIMEOUT_MS),
    ),
  ]);
} catch (e) {
  try {
    await run.cancel();
  } catch {
    /* ignore */
  }
  result = {
    status: "cancelled",
    timed_out: true,
    usage: run.usage,
    result: "",
    error: String(e.message || e),
  };
}
const text = result.result || "";
const pathsOk =
  /shared_lease|browser_session_manager/i.test(text) &&
  /agent_guidance/i.test(text);
const report = {
  trial: "pack answer-only tiny",
  status: result.status,
  timed_out: Boolean(result.timed_out),
  elapsed_ms: Date.now() - t0,
  agentId: agent.agentId,
  usage: result.usage,
  paths_ok: pathsOk,
  pass: pathsOk && !result.timed_out && result.status === "finished",
  result_preview: text.slice(0, 600),
};
const outPath = join(OUT, "trial_pack_answer_tiny.json");
writeFileSync(outPath, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
console.log(`[answer] wrote ${outPath}`);
process.exit(report.pass ? 0 : 2);
