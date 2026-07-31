"""Five deliberately different eval suites — no architecture may be tuned to these.

Design rule: each suite stresses ONE retrieval failure mode. Gold targets are
mostly disjoint across suites. Do not add arch-specific hints after seeing scores.

  S1_symbol       — path / identifier tokens in the query
  S2_paraphrase   — natural language, almost no code tokens
  S3_confusable   — near-miss siblings + negation
  S4_multihop     — answer is one hop from the obvious seed
  S5_terse        — 2–5 word ambiguous queries (high fan-out)
"""

from __future__ import annotations

S1_SYMBOL: list[dict] = [
    {
        "id": "s1_playbook_selector",
        "query": "coordination_intelligence planning playbook_selector.py PlaybookSelector",
        "files_substr": ["planning/playbook_selector.py", "playbook_selector.py"],
    },
    {
        "id": "s1_observe_bridge",
        "query": "resource_intelligence observe_bridge.py",
        "files_substr": ["observe_bridge.py"],
    },
    {
        "id": "s1_citation_readiness",
        "query": "seo_intelligence citation_readiness.py analyzer",
        "files_substr": ["citation_readiness.py"],
    },
    {
        "id": "s1_websocket_observer",
        "query": "visual_browser_intelligence live websocket_observer.py",
        "files_substr": ["websocket_observer.py"],
    },
    {
        "id": "s1_design_handlers",
        "query": "mcp design_intelligence_handlers.py",
        "files_substr": ["design_intelligence_handlers.py"],
    },
    {
        "id": "s1_null_impl",
        "query": "codebase_intelligence graph null_impl.py",
        "files_substr": ["graph/null_impl.py", "null_impl.py"],
    },
    {
        "id": "s1_crg_impl",
        "query": "codebase_intelligence graph crg_impl.py",
        "files_substr": ["graph/crg_impl.py", "crg_impl.py"],
    },
    {
        "id": "s1_route_claim",
        "query": "resolver_intelligence validators route_claim.py",
        "files_substr": ["validators/route_claim.py", "route_claim.py"],
    },
    {
        "id": "s1_icons_import",
        "query": "resource_intelligence import_verification icons.py",
        "files_substr": ["import_verification/icons.py"],
    },
    {
        "id": "s1_psm_normalize",
        "query": "coordination_intelligence psm normalize.py VERIFY_CAPABILITIES",
        "files_substr": ["psm/normalize.py"],
    },
    {
        "id": "s1_agent_integration",
        "query": "visual_browser_intelligence agent integration.py",
        "files_substr": ["agent/integration.py"],
    },
    {
        "id": "s1_distill_validators",
        "query": "coordination_layer distillation validators.py run_all_validations",
        "files_substr": ["distillation/validators.py"],
    },
]

S2_PARAPHRASE: list[dict] = [
    {
        "id": "s2_pick_playbook",
        "query": "chooses which coordination playbook should run given the current project situation",
        "files_substr": ["playbook_selector.py"],
    },
    {
        "id": "s2_resource_observe",
        "query": "bridges live browser observation into the resource intelligence ranking path",
        "files_substr": ["observe_bridge.py"],
    },
    {
        "id": "s2_ai_visibility",
        "query": "checks whether a page is ready to be cited by AI search systems",
        "files_substr": ["citation_readiness.py"],
    },
    {
        "id": "s2_ws_live",
        "query": "watches the page over a websocket while the visual browser session is live",
        "files_substr": ["websocket_observer.py"],
    },
    {
        "id": "s2_design_mcp_wire",
        "query": "wires design-intelligence perception tools into the MCP server dispatch table",
        "files_substr": ["design_intelligence_handlers.py"],
    },
    {
        "id": "s2_empty_graph",
        "query": "placeholder graph implementation used when no real code relationship graph exists",
        "files_substr": ["null_impl.py"],
    },
    {
        "id": "s2_real_graph",
        "query": "concrete code relationship graph backed by extracted repository structure",
        "files_substr": ["crg_impl.py"],
    },
    {
        "id": "s2_route_identity",
        "query": "validates whether a claimed frontend route actually matches project files",
        "files_substr": ["route_claim.py"],
    },
    {
        "id": "s2_icon_verify",
        "query": "verifies that icon imports referenced by resources resolve correctly",
        "files_substr": ["import_verification/icons.py"],
    },
    {
        "id": "s2_situation_normalize",
        "query": "normalizes the project situation model fields used by coordination planning",
        "files_substr": ["psm/normalize.py"],
    },
    {
        "id": "s2_agent_glue",
        "query": "glues the visual browser agent runner into the surrounding intelligence services",
        "files_substr": ["agent/integration.py"],
    },
    {
        "id": "s2_distill_checks",
        "query": "validation helpers that check distilled coordination artifacts before they ship",
        "files_substr": ["distillation/validators.py"],
    },
]

S3_CONFUSABLE: list[dict] = [
    {
        "id": "s3_null_not_crg",
        "query": "null graph stub when CRG is unavailable — not the real crg_impl extractor",
        "files_substr": ["null_impl.py"],
    },
    {
        "id": "s3_crg_not_null",
        "query": "real codebase relationship graph implementation — not the null placeholder",
        "files_substr": ["crg_impl.py"],
    },
    {
        "id": "s3_route_not_component_claim",
        "query": "route claim validator — not the component claim validator",
        "files_substr": ["route_claim.py"],
    },
    {
        "id": "s3_component_not_route_claim",
        "query": "component claim validator — not the route claim validator",
        "files_substr": ["component_claim.py"],
    },
    {
        "id": "s3_playbook_not_compiler",
        "query": "select which playbook applies — not the step compiler that emits tools",
        "files_substr": ["playbook_selector.py"],
    },
    {
        "id": "s3_compiler_not_selector",
        "query": "compile the active step into tools — not the playbook selector",
        "files_substr": ["step_compiler.py"],
    },
    {
        "id": "s3_design_handlers_not_coord",
        "query": "design intelligence MCP handlers — not coordination_handlers",
        "files_substr": ["design_intelligence_handlers.py"],
    },
    {
        "id": "s3_coord_handlers_not_design",
        "query": "coordination intelligence MCP handlers — not design_intelligence_handlers",
        "files_substr": ["coordination_handlers.py"],
    },
    {
        "id": "s3_mcp_session_not_browser_store",
        "query": "MCP session_store module — not visual browser session_store",
        "files_substr": ["navigation/mcp/session_store.py"],
    },
    {
        "id": "s3_browser_store_not_mcp",
        "query": "visual browser session_store — not the MCP session_store",
        "files_substr": ["browser/session_store.py", "visual_browser_intelligence/browser/session_store.py"],
    },
    {
        "id": "s3_guidance_not_instructions",
        "query": "degraded-code recovery guidance strings — not MCP_INSTRUCTIONS preamble",
        "files_substr": ["agent_guidance.py"],
    },
    {
        "id": "s3_instructions_not_guidance",
        "query": "host-agent MCP instructions preamble — not agent_guidance recovery map",
        "files_substr": ["mcp/instructions.py", "navigation/mcp/instructions.py"],
    },
]

S4_MULTIHOP: list[dict] = [
    {
        "id": "s4_selector_via_situation",
        "query": "given a project situation model, where is the playbook choice made",
        "files_substr": ["playbook_selector.py"],
    },
    {
        "id": "s4_normalize_via_governor",
        "query": "PSM fields the loop governor relies on after situation normalization",
        "files_substr": ["psm/normalize.py"],
    },
    {
        "id": "s4_icons_via_resources",
        "query": "resource import path that confirms icon packages are wired correctly",
        "files_substr": ["import_verification/icons.py"],
    },
    {
        "id": "s4_ws_via_live",
        "query": "live visual session channel that streams DOM updates without full re-observe",
        "files_substr": ["websocket_observer.py"],
    },
    {
        "id": "s4_citation_via_seo",
        "query": "SEO AI-visibility check for whether content can be attributed in answers",
        "files_substr": ["citation_readiness.py"],
    },
    {
        "id": "s4_bridge_via_resources",
        "query": "how resource ranking pulls fresh evidence from an active browser observe",
        "files_substr": ["observe_bridge.py"],
    },
    {
        "id": "s4_design_via_mcp",
        "query": "MCP entrypoints the host uses for design-sense / design-intelligence tools",
        "files_substr": ["design_intelligence_handlers.py"],
    },
    {
        "id": "s4_null_via_graph_pkg",
        "query": "fallback inside the codebase graph package when extraction produced nothing",
        "files_substr": ["null_impl.py"],
    },
    {
        "id": "s4_integration_via_agent",
        "query": "module that connects agent_runner to the rest of visual browser intelligence",
        "files_substr": ["agent/integration.py"],
    },
    {
        "id": "s4_distill_validators_via_build",
        "query": "checks invoked when distilled coordination YAML is validated before runtime publish",
        "files_substr": ["distillation/validators.py"],
    },
    {
        "id": "s4_route_via_resolver",
        "query": "resolver-intelligence check that a route identity claim is grounded in the repo",
        "files_substr": ["route_claim.py"],
    },
    {
        "id": "s4_crg_via_codebase",
        "query": "codebase intelligence graph that stores real file and symbol relationships",
        "files_substr": ["crg_impl.py"],
    },
]

S5_TERSE: list[dict] = [
    {
        "id": "s5_playbook_select",
        "query": "playbook selector",
        "files_substr": ["playbook_selector.py"],
    },
    {
        "id": "s5_observe_bridge",
        "query": "observe bridge",
        "files_substr": ["observe_bridge.py"],
    },
    {
        "id": "s5_websocket",
        "query": "websocket observer",
        "files_substr": ["websocket_observer.py"],
    },
    {
        "id": "s5_null_graph",
        "query": "null graph impl",
        "files_substr": ["null_impl.py"],
    },
    {
        "id": "s5_crg",
        "query": "crg impl",
        "files_substr": ["crg_impl.py"],
    },
    {
        "id": "s5_route_claim",
        "query": "route claim",
        "files_substr": ["route_claim.py"],
    },
    {
        "id": "s5_citation",
        "query": "citation readiness",
        "files_substr": ["citation_readiness.py"],
    },
    {
        "id": "s5_design_handlers",
        "query": "design intelligence handlers",
        "files_substr": ["design_intelligence_handlers.py"],
    },
    {
        "id": "s5_psm_norm",
        "query": "psm normalize",
        "files_substr": ["psm/normalize.py"],
    },
    {
        "id": "s5_icon_verify",
        "query": "icon import verification",
        "files_substr": ["import_verification/icons.py"],
    },
    {
        "id": "s5_agent_integration",
        "query": "agent integration",
        "files_substr": ["agent/integration.py"],
    },
    {
        "id": "s5_distill_validators",
        "query": "distillation validators",
        "files_substr": ["distillation/validators.py"],
    },
]

SUITES: dict[str, list[dict]] = {
    "S1_symbol": S1_SYMBOL,
    "S2_paraphrase": S2_PARAPHRASE,
    "S3_confusable": S3_CONFUSABLE,
    "S4_multihop": S4_MULTIHOP,
    "S5_terse": S5_TERSE,
}

SUITE_BLURBS: dict[str, str] = {
    "S1_symbol": "path/identifier tokens present",
    "S2_paraphrase": "natural language, few code tokens",
    "S3_confusable": "sibling disambiguation + negation",
    "S4_multihop": "answer one hop from obvious seed",
    "S5_terse": "2–5 word ambiguous queries",
}
