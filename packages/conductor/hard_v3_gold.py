"""Holdout hard_v3 gold — disjoint targets from hard_v2 (overfit check).

No primary gold files from hard_v2 (no recorder, distillation/build, mcp/server,
mcp/tools, browser_validator, perception_runtime, coordination_score,
execution harness, bootstrap, browser_session_manager as sole targets).

Buckets same as v2: symbol, paraphrase, confusable, multihop, distractor.
"""

from __future__ import annotations

HARD_V3: list[dict] = [
    # --- symbol ---
    {
        "id": "sym_agent_guidance",
        "bucket": "symbol",
        "query": "mcp agent_guidance.py degraded recovery actions deterministic",
        "files_substr": ["navigation/mcp/agent_guidance.py"],
    },
    {
        "id": "sym_mcp_instructions",
        "bucket": "symbol",
        "query": "mcp instructions.py MCP_INSTRUCTIONS preamble agent guide",
        "files_substr": ["navigation/mcp/instructions.py"],
    },
    {
        "id": "sym_tool_catalog",
        "bucket": "symbol",
        "query": "mcp tool_catalog.py tool schema listing",
        "files_substr": ["navigation/mcp/tool_catalog.py"],
    },
    {
        "id": "sym_preflight",
        "bucket": "symbol",
        "query": "visual_browser observe preflight.py condition waits",
        "files_substr": ["observe/preflight.py", "preflight.py"],
    },
    {
        "id": "sym_verification",
        "bucket": "symbol",
        "query": "visual_browser verify verification.py evaluate_js",
        "files_substr": ["verify/verification.py"],
    },
    {
        "id": "sym_loop_governor",
        "bucket": "symbol",
        "query": "coordination_intelligence loop_governor.py retry budgets playbook",
        "files_substr": ["planning/loop_governor.py", "loop_governor.py"],
    },
    {
        "id": "sym_step_compiler",
        "bucket": "symbol",
        "query": "coordination_intelligence step_compiler.py compiled_step tools",
        "files_substr": ["planning/step_compiler.py", "step_compiler.py"],
    },
    {
        "id": "sym_component_orch",
        "bucket": "symbol",
        "query": "component_intelligence orchestrator.py IntegrationPipeline",
        "files_substr": ["component_intelligence/orchestrator.py"],
    },
    {
        "id": "sym_workflow_scorer",
        "bucket": "symbol",
        "query": "coordination_validation scorer.py WorkflowScorer",
        "files_substr": ["coordination_validation/scorer.py"],
    },
    {
        "id": "sym_session_store_mcp",
        "bucket": "symbol",
        "query": "navigation mcp session_store.py persistence",
        "files_substr": ["navigation/mcp/session_store.py"],
    },
    # --- paraphrase ---
    {
        "id": "para_agent_guidance",
        "bucket": "paraphrase",
        "query": "deterministic recovery tips when perception tools return degraded error codes",
        "files_substr": ["navigation/mcp/agent_guidance.py"],
    },
    {
        "id": "para_instructions",
        "bucket": "paraphrase",
        "query": "long system preamble that tells the host coding agent how to loop observe reason act verify",
        "files_substr": ["navigation/mcp/instructions.py"],
    },
    {
        "id": "para_tool_catalog",
        "bucket": "paraphrase",
        "query": "catalog that enumerates MCP tool names and JSON argument schemas for the agent",
        "files_substr": ["navigation/mcp/tool_catalog.py"],
    },
    {
        "id": "para_preflight",
        "bucket": "paraphrase",
        "query": "wait for page readiness with condition checks instead of fixed sleep before observing",
        "files_substr": ["observe/preflight.py", "preflight.py"],
    },
    {
        "id": "para_verification",
        "bucket": "paraphrase",
        "query": "evaluate javascript assertions against the live browser page after an action",
        "files_substr": ["verify/verification.py"],
    },
    {
        "id": "para_loop_governor",
        "bucket": "paraphrase",
        "query": "advances multi-step coordination playbooks while enforcing retry budgets and invariants",
        "files_substr": ["loop_governor.py"],
    },
    {
        "id": "para_step_compiler",
        "bucket": "paraphrase",
        "query": "turns the active playbook step into concrete tool calls the coordinator can execute",
        "files_substr": ["step_compiler.py"],
    },
    {
        "id": "para_component_orch",
        "bucket": "paraphrase",
        "query": "end-to-end pipeline that searches providers and integrates a UI component into a repo",
        "files_substr": ["component_intelligence/orchestrator.py"],
    },
    {
        "id": "para_workflow_scorer",
        "bucket": "paraphrase",
        "query": "grades a recorded coordination run against the expected engineering workflow checklist",
        "files_substr": ["coordination_validation/scorer.py"],
    },
    {
        "id": "para_agent_runner",
        "bucket": "paraphrase",
        "query": "runs the visual browser agent loop that drives tools for a navigation episode",
        "files_substr": ["agent/agent_runner.py", "agent_runner.py"],
    },
    # --- confusable ---
    {
        "id": "conf_guidance_not_instructions",
        "bucket": "confusable",
        "query": "short degraded-code recovery strings for tools — not the long MCP host preamble text",
        "files_substr": ["navigation/mcp/agent_guidance.py"],
    },
    {
        "id": "conf_catalog_not_tools",
        "bucket": "confusable",
        "query": "tool catalog listing module, not the live tools.py registration handlers",
        "files_substr": ["navigation/mcp/tool_catalog.py"],
    },
    {
        "id": "conf_mcp_session_not_browser",
        "bucket": "confusable",
        "query": "MCP-level session persistence store, not the visual browser session_store",
        "files_substr": ["navigation/mcp/session_store.py"],
    },
    {
        "id": "conf_scorer_not_coord_score",
        "bucket": "confusable",
        "query": "WorkflowScorer that grades recorded decisions — not coordination_score aggregation",
        "files_substr": ["coordination_validation/scorer.py"],
    },
    {
        "id": "conf_governor_not_compiler",
        "bucket": "confusable",
        "query": "retry budget and playbook progression governor, not the step tool compiler",
        "files_substr": ["loop_governor.py"],
    },
    {
        "id": "conf_preflight_not_verify",
        "bucket": "confusable",
        "query": "pre-observe readiness waits, not post-action javascript verification helpers",
        "files_substr": ["observe/preflight.py", "preflight.py"],
    },
    {
        "id": "conf_component_not_seo_orch",
        "bucket": "confusable",
        "query": "component intelligence integration orchestrator, not the SEO planning orchestrator",
        "files_substr": ["component_intelligence/orchestrator.py"],
    },
    {
        "id": "conf_claim_component_not_route",
        "bucket": "confusable",
        "query": "validator for component identity claims, not route claim validation",
        "files_substr": ["validators/component_claim.py", "component_claim.py"],
    },
    # --- multihop ---
    {
        "id": "hop_guidance_via_mcp",
        "bucket": "multihop",
        "query": "where MCP surfaces recovery actions when a perception tool comes back degraded",
        "files_substr": ["navigation/mcp/agent_guidance.py"],
    },
    {
        "id": "hop_governor_via_coord_intel",
        "bucket": "multihop",
        "query": "coordination intelligence module that decides when to advance or retry a playbook step",
        "files_substr": ["loop_governor.py"],
    },
    {
        "id": "hop_compiler_via_briefing",
        "bucket": "multihop",
        "query": "builds the compiled_step tool list that appears inside coordinator briefings",
        "files_substr": ["step_compiler.py"],
    },
    {
        "id": "hop_preflight_via_observe",
        "bucket": "multihop",
        "query": "observe-path helper that replaces sleep with URL and readiness condition checks",
        "files_substr": ["observe/preflight.py", "preflight.py"],
    },
    {
        "id": "hop_scorer_via_recorder",
        "bucket": "multihop",
        "query": "after decisions are recorded, which module scores the coordination workflow outcome",
        "files_substr": ["coordination_validation/scorer.py"],
    },
    {
        "id": "hop_handlers_design",
        "bucket": "multihop",
        "query": "MCP handler wiring for design-intelligence perception tools",
        "files_substr": ["mcp/design_intelligence_handlers.py", "design_intelligence_handlers.py"],
    },
    {
        "id": "hop_coord_handlers",
        "bucket": "multihop",
        "query": "MCP handlers that expose coordination-intelligence tools to the host agent",
        "files_substr": ["mcp/coordination_handlers.py", "coordination_handlers.py"],
    },
    {
        "id": "hop_workflows_coord",
        "bucket": "multihop",
        "query": "definitions of expected coordination validation workflows used during scoring",
        "files_substr": ["coordination_validation/workflows.py"],
    },
    # --- distractor ---
    {
        "id": "dist_guidance_not_seo",
        "bucket": "distractor",
        "query": "recovery guidance for degraded perception codes — ignore SEO audit scripts",
        "files_substr": ["navigation/mcp/agent_guidance.py"],
    },
    {
        "id": "dist_governor_not_figma",
        "bucket": "distractor",
        "query": "playbook loop governor in coordination intelligence — not figma community scripts",
        "files_substr": ["loop_governor.py"],
    },
    {
        "id": "dist_preflight_not_seo_verify",
        "bucket": "distractor",
        "query": "browser observe preflight waits — not SEO verification loop",
        "files_substr": ["observe/preflight.py", "preflight.py"],
    },
    {
        "id": "dist_component_orch_not_consistency",
        "bucket": "distractor",
        "query": "component integration orchestrator — not consistency discovery pipelines",
        "files_substr": ["component_intelligence/orchestrator.py"],
    },
    {
        "id": "dist_instructions_not_agent_runner",
        "bucket": "distractor",
        "query": "static MCP instruction preamble for the host — not the visual agent runner loop",
        "files_substr": ["navigation/mcp/instructions.py"],
    },
    {
        "id": "dist_claim_not_browser_validator",
        "bucket": "distractor",
        "query": "static component claim validator in resolver intelligence — not live browser_validator",
        "files_substr": ["component_claim.py", "validators/component_claim.py"],
    },
]
