#!/usr/bin/env node
/** Answer-only from existing Context Agent pack (no tools). */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Agent } from "@cursor/sdk";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../../..");
const OUT = resolve(ROOT, "out/experiments/cursor_sdk_ab");
const WORK = resolve(ROOT, "testdata/cursor_sdk_ab/work_d_channel_best_mcponly");

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
  readFileSync(join(OUT, "sdk_trial_context_pack.json"), "utf8"),
);
const slim = {
  summary: pack.summary,
  files: (pack.files || []).slice(0, 8),
  hits: (pack.snippets || [])
    .filter((s) => s.kind === "search_hit")
    .slice(0, 5)
    .map((s) => ({
      file: s.file,
      lines: [s.start_line, s.end_line],
      why: (s.why || "").slice(0, 100),
    })),
};

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
  JSON.stringify(
    {
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
    },
    null,
    2,
  ),
);

const prompt = `ANSWER NOW. Do not call any tools.

CONTEXT_PACK:
${JSON.stringify(slim, null, 2)}

List exact paths only:
1) lease/busy/acquire
2) agent guidance
`;

const t0 = Date.now();
await using agent = await Agent.create({
  apiKey: process.env.CURSOR_API_KEY,
  name: `ctx-pack-answer-${Date.now()}`,
  model: { id: "composer-2.5" },
  local: { cwd: WORK, settingSources: ["project"] },
});
console.log("agentId", agent.agentId);
const run = await agent.send(prompt);
let result;
try {
  result = await Promise.race([
    run.wait(),
    new Promise((_, rej) =>
      setTimeout(() => rej(new Error("TIMEOUT 90s")), 90000),
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
const usage = result.usage || run.usage || {};
const text = (result.result || "").slice(0, 1000);
const report = {
  trial: "pack-answer-only",
  status: result.status,
  timed_out: Boolean(result.timed_out),
  elapsed_ms: Date.now() - t0,
  totalTokens: usage.totalTokens ?? null,
  pass_hint: /shared_lease|browser_session_manager|agent_guidance/.test(text),
  result_preview: text,
};
writeFileSync(
  join(OUT, "trial_context_agent_sdk_answer.json"),
  JSON.stringify(report, null, 2),
);
console.log(JSON.stringify(report, null, 2));
process.exit(report.pass_hint ? 0 : 2);
