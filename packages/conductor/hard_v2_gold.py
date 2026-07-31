"""Tough hard_v2 gold queries for conductor architecture bake-off.

Buckets:
  symbol   — identifier / path tokens present
  paraphrase — natural language, few code tokens
  confusable — near-miss siblings (validator vs models vs contract)
  multihop — answer lives one hop from an obvious seed
  distractor — easy wrong sibling must not win @5
"""

from __future__ import annotations

# Each entry: id, bucket, query, files_substr (any match counts as hit), optional alts
HARD_V2: list[dict] = [
    # --- symbol ---
    {
        "id": "sym_mcp_server",
        "bucket": "symbol",
        "query": "navigation mcp server.py entrypoint register tools",
        "files_substr": ["navigation/mcp/server.py"],
    },
    {
        "id": "sym_mcp_tools",
        "bucket": "symbol",
        "query": "mcp tools.py perception tool definitions catalog",
        "files_substr": ["navigation/mcp/tools.py"],
    },
    {
        "id": "sym_browser_session_manager",
        "bucket": "symbol",
        "query": "browser_session_manager connect disconnect reuse session",
        "files_substr": ["browser_session_manager.py"],
    },
    {
        "id": "sym_perception_runtime",
        "bucket": "symbol",
        "query": "perception_runtime.py inspiration intelligence browser",
        "files_substr": ["perception_runtime.py"],
    },
    {
        "id": "sym_coordination_score",
        "bucket": "symbol",
        "query": "coordination_score.py compute score multi agent",
        "files_substr": ["coordination_score.py"],
    },
    {
        "id": "sym_execution_harness",
        "bucket": "symbol",
        "query": "execution_validation harness.py record browser outcomes",
        "files_substr": ["execution_validation/harness.py"],
    },
    {
        "id": "sym_workflow_recorder",
        "bucket": "symbol",
        "query": "coordination_validation recorder.py workflow traces",
        "files_substr": ["coordination_validation/recorder.py"],
    },
    {
        "id": "sym_bootstrap",
        "bucket": "symbol",
        "query": "_bootstrap.py load navigation package modules ROOT",
        "files_substr": ["_bootstrap.py"],
    },
    {
        "id": "sym_distillation_build",
        "bucket": "symbol",
        "query": "coordination_layer distillation build.py pipeline",
        "files_substr": ["coordination_layer/distillation/build.py", "distillation/build.py"],
    },
    {
        "id": "sym_browser_validator",
        "bucket": "symbol",
        "query": "browser_validator.py component intelligence live browser",
        "files_substr": ["validation/browser_validator.py", "browser_validator.py"],
    },
    # --- paraphrase ---
    {
        "id": "para_mcp_entry",
        "bucket": "paraphrase",
        "query": "where does the MCP server spin up and expose frontend perception tools to the coding agent",
        "files_substr": ["navigation/mcp/server.py"],
    },
    {
        "id": "para_tool_catalog",
        "bucket": "paraphrase",
        "query": "list of tool schemas the agent can call for observing the browser and DOM",
        "files_substr": ["navigation/mcp/tools.py"],
    },
    {
        "id": "para_session_lifecycle",
        "bucket": "paraphrase",
        "query": "manage connect disconnect and reuse of browser-use sessions for visual navigation",
        "files_substr": ["browser_session_manager.py"],
    },
    {
        "id": "para_no_llm_runtime",
        "bucket": "paraphrase",
        "query": "deterministic browser observation runtime that does not run an LLM inside the MCP process",
        "files_substr": ["perception_runtime.py", "navigation/mcp/instructions.py"],
    },
    {
        "id": "para_coord_score",
        "bucket": "paraphrase",
        "query": "numeric score for how well multi-agent frontend navigation validation coordinated",
        "files_substr": ["coordination_score.py"],
    },
    {
        "id": "para_exec_harness",
        "bucket": "paraphrase",
        "query": "harness that logs whether browser actions succeeded during execution validation",
        "files_substr": ["execution_validation/harness.py"],
    },
    {
        "id": "para_trace_recorder",
        "bucket": "paraphrase",
        "query": "persist coordination workflow traces so scoring can replay what agents did",
        "files_substr": ["coordination_validation/recorder.py"],
    },
    {
        "id": "para_distill_pipeline",
        "bucket": "paraphrase",
        "query": "build step that validates distilled navigation knowledge in the coordination layer",
        "files_substr": ["distillation/build.py"],
    },
    {
        "id": "para_component_live_check",
        "bucket": "paraphrase",
        "query": "validate UI components against a live browser for component intelligence",
        "files_substr": ["browser_validator.py"],
    },
    {
        "id": "para_visual_browser",
        "bucket": "paraphrase",
        "query": "orchestrate screenshot and DOM grounded visual browser intelligence sessions",
        "files_substr": ["visual_browser_intelligence"],
    },
    # --- confusable ---
    {
        "id": "conf_validator_not_models",
        "bucket": "confusable",
        "query": "live browser validation of components — not the pydantic models or claim validators",
        "files_substr": ["validation/browser_validator.py", "browser_validator.py"],
    },
    {
        "id": "conf_recorder_not_harness",
        "bucket": "confusable",
        "query": "store workflow traces for later scoring, not the coordination harness runner itself",
        "files_substr": ["coordination_validation/recorder.py"],
    },
    {
        "id": "conf_tools_not_instructions",
        "bucket": "confusable",
        "query": "machine-readable MCP tool definitions, not the human-facing instruction prompt text",
        "files_substr": ["navigation/mcp/tools.py"],
    },
    {
        "id": "conf_server_not_handlers",
        "bucket": "confusable",
        "query": "MCP server process entry that registers tools, not per-tool handler implementations",
        "files_substr": ["navigation/mcp/server.py"],
    },
    {
        "id": "conf_session_mgr_not_store",
        "bucket": "confusable",
        "query": "lifecycle manager for browser-use sessions rather than the session store helper",
        "files_substr": ["browser_session_manager.py"],
    },
    {
        "id": "conf_score_not_harness",
        "bucket": "confusable",
        "query": "function that computes the coordination score metric, not the validation harness loop",
        "files_substr": ["coordination_score.py"],
    },
    {
        "id": "conf_exec_not_coord_harness",
        "bucket": "confusable",
        "query": "execution-layer validation harness for browser action outcomes, not coordination_validation harness",
        "files_substr": ["execution_validation/harness.py"],
    },
    {
        "id": "conf_crg_impl_not_null",
        "bucket": "confusable",
        "query": "real code review graph implementation when CRG is available, not the null stub",
        "files_substr": ["crg_impl.py", "codebase_intelligence/graph/crg"],
    },
    # --- multihop ---
    {
        "id": "hop_tools_via_server",
        "bucket": "multihop",
        "query": "after the MCP server starts, which module defines the actual tool schemas it registers",
        "files_substr": ["navigation/mcp/tools.py"],
    },
    {
        "id": "hop_score_via_harness",
        "bucket": "multihop",
        "query": "module the coordination harness uses to turn workflow outcomes into a numeric score",
        "files_substr": ["coordination_score.py"],
    },
    {
        "id": "hop_recorder_via_coord",
        "bucket": "multihop",
        "query": "where coordination validation persists traces that scoring later consumes",
        "files_substr": ["coordination_validation/recorder.py"],
    },
    {
        "id": "hop_validator_via_component",
        "bucket": "multihop",
        "query": "under component intelligence, the live-browser check used to validate UI pieces",
        "files_substr": ["browser_validator.py"],
    },
    {
        "id": "hop_runtime_via_inspiration",
        "bucket": "multihop",
        "query": "inspiration intelligence browser path that drives observation without embedding an LLM",
        "files_substr": ["perception_runtime.py"],
    },
    {
        "id": "hop_bootstrap_via_runners",
        "bucket": "multihop",
        "query": "shared bootstrap imported by run_* scripts to set ROOT and load navigation packages",
        "files_substr": ["_bootstrap.py"],
    },
    {
        "id": "hop_distill_via_coord_layer",
        "bucket": "multihop",
        "query": "coordination_layer distillation entry that builds and validates distilled knowledge",
        "files_substr": ["distillation/build.py"],
    },
    {
        "id": "hop_handlers_via_mcp",
        "bucket": "multihop",
        "query": "handlers wired by the MCP package that dispatch tool calls for perception",
        "files_substr": ["navigation/mcp/handlers.py"],
    },
    # --- distractor pressure ---
    {
        "id": "dist_avoid_seo_browser",
        "bucket": "distractor",
        "query": "visual browser intelligence session manager for perception — ignore SEO provider browsers",
        "files_substr": ["browser_session_manager.py", "visual_browser_intelligence"],
    },
    {
        "id": "dist_avoid_claim_validator",
        "bucket": "distractor",
        "query": "component live browser validator in component_intelligence validation package",
        "files_substr": ["component_intelligence/validation/browser_validator.py", "validation/browser_validator.py"],
    },
    {
        "id": "dist_avoid_figma_coord",
        "bucket": "distractor",
        "query": "coordination_layer distillation build, not figma coordination coordinator",
        "files_substr": ["coordination_layer/distillation/build.py", "distillation/build.py"],
    },
    {
        "id": "dist_avoid_consistency_pipeline",
        "bucket": "distractor",
        "query": "execution validation harness recording browser action results",
        "files_substr": ["execution_validation/harness.py"],
    },
    {
        "id": "dist_mcp_instructions_principle",
        "bucket": "distractor",
        "query": "instructions describing that the MCP is a deterministic evidence runtime and the agent is the brain",
        "files_substr": ["navigation/mcp/instructions.py", "navigation/mcp/server.py"],
    },
    {
        "id": "dist_null_vs_crg",
        "bucket": "distractor",
        "query": "null code graph stub used when CRG is unavailable so browser automation continues",
        "files_substr": ["null_impl.py", "graph/null"],
    },
]
