#!/usr/bin/env node
/**
 * Install per-arm Cursor rules/hooks.
 *
 * mode=d_rerank_read  — search_code first, native Read/Grep ALLOWED (yesterday style)
 * mode=graphify_force — deny native explore; graphify MCP only
 */
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";

function installDRerankRead(workDir) {
  const rule = `---
description: D_rerank search first, then native Read on hit files
alwaysApply: true
---

# D_rerank → Read → Edit

1. Call **context-engine search_code** first (1–2×) for vague NL locate.
2. **Read** the returned hit files (native Read is allowed and expected).
3. Edit + pytest ≤2.

Do not reindex. Stay in this workspace. Do not spam search_code.
`;
  const rules = join(workDir, ".cursor", "rules");
  const hooks = join(workDir, ".cursor", "hooks");
  mkdirSync(rules, { recursive: true });
  mkdirSync(hooks, { recursive: true });
  writeFileSync(join(rules, "mcp-first.mdc"), rule, "utf8");
  writeFileSync(
    join(hooks, "prefer-mcp.cjs"),
    `process.stdout.write(JSON.stringify({ permission: "allow" }));\n`,
    "utf8",
  );
  writeFileSync(
    join(workDir, ".cursor", "hooks.json"),
    JSON.stringify({ version: 1, hooks: {} }, null, 2) + "\n",
    "utf8",
  );
}

function installGraphifyForce(workDir) {
  const rule = `---
description: Graphify MCP only for discovery
alwaysApply: true
---

# Graphify MCP

Built-in Read / Grep / Glob / SemanticSearch are blocked.

Use **query_graph** → **get_node** / **get_neighbors** → Edit → pytest ≤2.
`;
  const hookJs = `const fs = require("fs");
let raw = "";
try { raw = fs.readFileSync(0, "utf8"); } catch { raw = ""; }
let payload = {};
try { payload = JSON.parse(raw || "{}"); } catch { payload = {}; }
const tool = String(payload.tool_name || payload.toolName || "");
const blocked = new Set(["Read", "Grep", "Glob", "SemanticSearch", "SemSearch", "Ripgrep"]);
if (blocked.has(tool)) {
  process.stdout.write(JSON.stringify({
    permission: "deny",
    user_message: tool + " blocked — use graphify MCP",
    agent_message: tool + " blocked. Use query_graph, get_node, get_neighbors. Then Edit.",
  }));
  process.exit(0);
}
process.stdout.write(JSON.stringify({ permission: "allow" }));
`;
  const rules = join(workDir, ".cursor", "rules");
  const hooks = join(workDir, ".cursor", "hooks");
  mkdirSync(rules, { recursive: true });
  mkdirSync(hooks, { recursive: true });
  writeFileSync(join(rules, "mcp-first.mdc"), rule, "utf8");
  writeFileSync(join(hooks, "prefer-mcp.cjs"), hookJs, "utf8");
  writeFileSync(
    join(workDir, ".cursor", "hooks.json"),
    JSON.stringify(
      {
        version: 1,
        hooks: {
          preToolUse: [
            {
              matcher: "Read|Grep|Glob|SemanticSearch",
              command: "node .cursor/hooks/prefer-mcp.cjs",
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

/** @deprecated use installForArm */
export function installMcpPrefer(workDir) {
  installDRerankRead(workDir);
}

export function installForArm(workDir, arm) {
  if (arm === "graphify") installGraphifyForce(workDir);
  else installDRerankRead(workDir);
}

if (process.argv[1] && process.argv[1].includes("install_mcp_prefer")) {
  const target = process.argv[2];
  const mode = process.argv[3] || "d_rerank_read";
  if (!target || !existsSync(target)) {
    console.error("usage: node install_mcp_prefer.mjs <workDir> [d_rerank_read|graphify_force]");
    process.exit(2);
  }
  if (mode === "graphify_force") installGraphifyForce(target);
  else installDRerankRead(target);
  console.log("installed", mode, "into", target);
}
