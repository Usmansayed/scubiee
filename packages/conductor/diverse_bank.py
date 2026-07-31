"""Diverse holdout bank — domains/styles NOT used in suite_bank or hard_v2/v3 design.

LOCKED as a gate: do not invent architecture features by staring at these queries.
If an R&D change only helps suites/v2/v3 but drops diverse macro, REJECT.

Suites:
  D1_seo_domain      — SEO / AI-visibility modules
  D2_figma_domain    — Figma intelligence
  D3_consistency     — consistency intelligence
  D4_design_exec     — design-sense + execution runtime
  D5_errorish        — error/recovery/policy phrasing (still no LLM)
"""

from __future__ import annotations

D1_SEO: list[dict] = [
    {
        "id": "d1_llms_txt",
        "query": "seo_intelligence ai_visibility analyzers llms_txt.py",
        "files_substr": ["analyzers/llms_txt.py", "llms_txt.py"],
    },
    {
        "id": "d1_schema_quality",
        "query": "schema_quality.py structured data AI visibility analyzer",
        "files_substr": ["analyzers/schema_quality.py", "schema_quality.py"],
    },
    {
        "id": "d1_crawlability",
        "query": "crawlability.py analyzer whether bots can fetch the page",
        "files_substr": ["analyzers/crawlability.py", "crawlability.py"],
    },
    {
        "id": "d1_verification_loop",
        "query": "seo verification loop.py re-check recommendations after fixes",
        "files_substr": ["seo_intelligence/verification/loop.py"],
    },
    {
        "id": "d1_codebase_bridge",
        "query": "seo reasoning codebase_bridge.py map issues back to repo files",
        "files_substr": ["reasoning/codebase_bridge.py"],
    },
    {
        "id": "d1_para_llms",
        "query": "checks whether a site published guidance that AI crawlers should read",
        "files_substr": ["llms_txt.py"],
    },
    {
        "id": "d1_para_schema",
        "query": "grades how usable on-page structured data is for answer engines",
        "files_substr": ["schema_quality.py"],
    },
    {
        "id": "d1_para_verify_seo",
        "query": "after proposing SEO fixes, re-run checks to confirm they actually landed",
        "files_substr": ["seo_intelligence/verification/loop.py"],
    },
    {
        "id": "d1_conf_bing_not_google",
        "query": "Bing webmaster OAuth helper — not the Google Search Console auth module",
        "files_substr": ["auth/bing.py", "seo_intelligence/auth/bing.py"],
    },
    {
        "id": "d1_terse_faq",
        "query": "faq answer blocks analyzer",
        "files_substr": ["faq_answer_blocks.py"],
    },
]

D2_FIGMA: list[dict] = [
    {
        "id": "d2_token_store",
        "query": "figma_intelligence connection token_store.py PAT persistence",
        "files_substr": ["connection/token_store.py", "figma_intelligence/connection/token_store.py"],
    },
    {
        "id": "d2_file_key_resolver",
        "query": "community_duplication file_key_resolver.py",
        "files_substr": ["file_key_resolver.py"],
    },
    {
        "id": "d2_deep_review",
        "query": "figma review deep_review.py",
        "files_substr": ["review/deep_review.py", "figma_intelligence/review/deep_review.py"],
    },
    {
        "id": "d2_ranker",
        "query": "figma_intelligence ranking ranker.py",
        "files_substr": ["figma_intelligence/ranking/ranker.py"],
    },
    {
        "id": "d2_para_token",
        "query": "where the Figma personal access token is stored after connect",
        "files_substr": ["connection/token_store.py", "token_store.py"],
    },
    {
        "id": "d2_para_duplicate",
        "query": "resolves a Figma community file key before duplication into the workspace",
        "files_substr": ["file_key_resolver.py"],
    },
    {
        "id": "d2_para_rank",
        "query": "scores competing Figma design candidates for the current intent",
        "files_substr": ["figma_intelligence/ranking/ranker.py", "ranking/ranker.py"],
    },
    {
        "id": "d2_conf_http_not_browser",
        "query": "HTTP backend for Figma community discovery — not the Playwright community browser",
        "files_substr": ["community_adapter/backends/http.py", "backends/http.py"],
    },
    {
        "id": "d2_conf_inferrer_not_normalizer",
        "query": "candidate intelligence inferrer — not the candidate normalizer",
        "files_substr": ["candidate_intelligence/inferrer.py", "inferrer.py"],
    },
    {
        "id": "d2_terse_health",
        "query": "figma health monitor",
        "files_substr": ["figma_intelligence/health/monitor.py", "health/monitor.py"],
    },
]

D3_CONSISTENCY: list[dict] = [
    {
        "id": "d3_snapshot_gate",
        "query": "consistency_intelligence benchmark snapshot_gate.py",
        "files_substr": ["benchmark/snapshot_gate.py", "snapshot_gate.py"],
    },
    {
        "id": "d3_fix_proposer",
        "query": "consistency consumers fix_proposer.py",
        "files_substr": ["consumers/fix_proposer.py", "fix_proposer.py"],
    },
    {
        "id": "d3_graph_persistence",
        "query": "consistency_intelligence graph persistence.py",
        "files_substr": ["consistency_intelligence/graph/persistence.py"],
    },
    {
        "id": "d3_tokens_source",
        "query": "consistency discovery sources tokens.py",
        "files_substr": ["discovery/sources/tokens.py"],
    },
    {
        "id": "d3_para_fix",
        "query": "proposes concrete consistency fixes from audited design-graph gaps",
        "files_substr": ["fix_proposer.py"],
    },
    {
        "id": "d3_para_gate",
        "query": "benchmark gate that decides whether a consistency snapshot is good enough to ship",
        "files_substr": ["snapshot_gate.py"],
    },
    {
        "id": "d3_para_tokens",
        "query": "discovery source that ingests design tokens into the consistency graph",
        "files_substr": ["discovery/sources/tokens.py"],
    },
    {
        "id": "d3_conf_auditor_not_validator",
        "query": "consistency auditor consumer — not the consistency validator consumer",
        "files_substr": ["consumers/auditor.py"],
    },
    {
        "id": "d3_conf_figma_src_not_codebase",
        "query": "consistency discovery from Figma — not the codebase discovery source",
        "files_substr": ["discovery/sources/figma.py"],
    },
    {
        "id": "d3_terse_envelope",
        "query": "consistency knowledge envelope",
        "files_substr": ["consistency_intelligence/knowledge/envelope.py", "knowledge/envelope.py"],
    },
]

D4_DESIGN_EXEC: list[dict] = [
    {
        "id": "d4_a11y_reviewer",
        "query": "design_sense_intelligence reviewers accessibility.py",
        "files_substr": ["reviewers/accessibility.py"],
    },
    {
        "id": "d4_typography",
        "query": "design_sense reviewers typography.py",
        "files_substr": ["reviewers/typography.py"],
    },
    {
        "id": "d4_uicrit",
        "query": "design_sense workflows uicrit_pipeline.py",
        "files_substr": ["workflows/uicrit_pipeline.py", "uicrit_pipeline.py"],
    },
    {
        "id": "d4_dispatch_registry",
        "query": "execution_runtime dispatch_registry.py",
        "files_substr": ["execution_runtime/dispatch_registry.py"],
    },
    {
        "id": "d4_idempotency",
        "query": "execution_runtime idempotency.py",
        "files_substr": ["execution_runtime/idempotency.py"],
    },
    {
        "id": "d4_para_a11y",
        "query": "reviews UI snapshots for accessibility issues in design-sense",
        "files_substr": ["reviewers/accessibility.py"],
    },
    {
        "id": "d4_para_dispatch",
        "query": "registry that maps execution runtime tool names to handler callables",
        "files_substr": ["dispatch_registry.py"],
    },
    {
        "id": "d4_para_idempotent",
        "query": "ensures repeated execution-runtime tool calls do not double-apply side effects",
        "files_substr": ["idempotency.py"],
    },
    {
        "id": "d4_conf_retry_not_timeout",
        "query": "execution retry policy — not the timeout policy module",
        "files_substr": ["policies/retry.py"],
    },
    {
        "id": "d4_terse_ledger",
        "query": "execution runtime ledger",
        "files_substr": ["execution_runtime/ledger.py"],
    },
]

D5_ERRORISH: list[dict] = [
    {
        "id": "d5_recovery_policy",
        "query": "execution_runtime policies recovery.py degraded tool recovery",
        "files_substr": ["policies/recovery.py"],
    },
    {
        "id": "d5_failures_policy",
        "query": "execution_runtime policies failures.py",
        "files_substr": ["policies/failures.py"],
    },
    {
        "id": "d5_cancellation",
        "query": "execution_runtime policies cancellation.py",
        "files_substr": ["policies/cancellation.py"],
    },
    {
        "id": "d5_safe_tools",
        "query": "execution_runtime policies safe_tools.py",
        "files_substr": ["policies/safe_tools.py"],
    },
    {
        "id": "d5_para_recover",
        "query": "policy that decides how to recover when an execution tool returns degraded",
        "files_substr": ["policies/recovery.py"],
    },
    {
        "id": "d5_para_cancel",
        "query": "rules for aborting in-flight execution-runtime work cleanly",
        "files_substr": ["policies/cancellation.py"],
    },
    {
        "id": "d5_para_safe",
        "query": "allowlist of tools considered safe to auto-retry in the execution runtime",
        "files_substr": ["policies/safe_tools.py"],
    },
    {
        "id": "d5_conf_recovery_not_retry",
        "query": "degraded-state recovery policy — not the generic retry backoff policy",
        "files_substr": ["policies/recovery.py"],
    },
    {
        "id": "d5_conf_failures_not_tier",
        "query": "failure classification policy — not the execution tier policy",
        "files_substr": ["policies/failures.py"],
    },
    {
        "id": "d5_terse_handler_runner",
        "query": "handler runner",
        "files_substr": ["execution_runtime/handler_runner.py", "handler_runner.py"],
    },
]

DIVERSE_SUITES: dict[str, list[dict]] = {
    "D1_seo_domain": D1_SEO,
    "D2_figma_domain": D2_FIGMA,
    "D3_consistency": D3_CONSISTENCY,
    "D4_design_exec": D4_DESIGN_EXEC,
    "D5_errorish": D5_ERRORISH,
}

DIVERSE_BLURBS: dict[str, str] = {
    "D1_seo_domain": "SEO / AI-visibility domain (new packages)",
    "D2_figma_domain": "Figma intelligence domain",
    "D3_consistency": "Consistency intelligence domain",
    "D4_design_exec": "Design-sense + execution runtime",
    "D5_errorish": "Policy/error/recovery phrasing",
}
