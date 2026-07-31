"""Locked soft-query gold bank from OpenCode soft-30 agent ratings.

LOCKED as a soft-traffic gate: do not invent architecture features by staring
at these queries. Use only for bake-off / accept-reject.

Buckets (from OpenCode sheet — slice metrics, not training labels):
  d_win      — D uniquely or clearly better on soft judgment
  g_win      — Graphify uniquely or clearly better (D dropped the hit)
  tie        — both useful at similar rank
  miss_both  — neither top-5 had the needed file
"""

from __future__ import annotations

SOFT_BANK: list[dict] = [
    {
        "id": "soft01_playbook_next",
        "query": "how does the system decide what to do next based on what kind of app we are building",
        "files_substr": ["playbook_selector.py"],
        "bucket": "miss_both",
    },
    {
        "id": "soft02_quick_fix_skip",
        "query": "where are the rules for skipping certain steps if the user just wants a quick fix",
        "files_substr": ["effort_allocator.py"],
        "bucket": "g_win",
    },
    {
        "id": "soft03_parallel_groups",
        "query": "how do we organize tasks into groups that can run at the same time",
        "files_substr": ["cluster_resolver.py"],
        "bucket": "miss_both",
    },
    {
        "id": "soft04_webpage_connect",
        "query": "how does the agent connect to the running webpage to see what it looks like",
        "files_substr": ["websocket_observer.py"],
        "bucket": "miss_both",
    },
    {
        "id": "soft05_visible_elements",
        "query": "where do we capture what elements are visible on the screen right now",
        "files_substr": ["visual_capture.py"],
        "bucket": "tie",
    },
    {
        "id": "soft06_button_effect",
        "query": "how do we check if a button actually did something after we clicked it",
        "files_substr": ["scripted_actions.py"],
        "bucket": "d_win",
    },
    {
        "id": "soft07_graph_not_ready",
        "query": "what happens if we try to look up code dependencies but the graph database isn't ready",
        "files_substr": ["null_impl.py"],
        "bucket": "d_win",
    },
    {
        "id": "soft08_route_to_source",
        "query": "how does the system map a web address route to the actual source code file that renders it",
        "files_substr": ["codebase_bridge.py"],
        "bucket": "tie",
    },
    {
        "id": "soft09_robots_block",
        "query": "where do we look to see if the robots text file blocks search engines",
        "files_substr": ["crawlability.py"],
        "bucket": "d_win",
    },
    {
        "id": "soft10_chatbot_content",
        "query": "how do we analyze a page to see if chat bots can understand its content",
        "files_substr": ["content_structure.py"],
        "bucket": "tie",
    },
    {
        "id": "soft11_seo_verify",
        "query": "after making search engine optimizations, how do we make sure they actually worked",
        "files_substr": ["recommendations/engine.py", "seo_intelligence/recommendations/engine.py"],
        "bucket": "d_win",
    },
    {
        "id": "soft12_social_meta",
        "query": "where do we check if the website has the right meta tags for social media previews",
        "files_substr": ["citation_readiness.py"],
        "bucket": "d_win",
    },
    {
        "id": "soft13_design_spacing",
        "query": "how do we talk to the design tool to get colors and spacing",
        "files_substr": ["extractors/spacing.py"],
        "bucket": "d_win",
    },
    {
        "id": "soft14_design_auth_keys",
        "query": "where do we save the authentication keys for the design tool",
        "files_substr": ["token_store.py"],
        "bucket": "g_win",
    },
    {
        "id": "soft15_live_vs_mockup",
        "query": "how does the system compare the live site against the original mockup to find differences",
        "files_substr": ["live/correlate.py"],
        "bucket": "tie",
    },
    {
        "id": "soft16_ui_consistency",
        "query": "where do we enforce that the user interface looks the same across different pages",
        "files_substr": ["graph/pages.py"],
        "bucket": "d_win",
    },
    {
        "id": "soft17_design_snapshot",
        "query": "how do we take a picture of the design system standards to use later",
        "files_substr": ["integrations/designlang.py"],
        "bucket": "d_win",
    },
    {
        "id": "soft18_visual_rules_block",
        "query": "what stops a design change from going live if it breaks our visual rules",
        "files_substr": ["design_lint/methodology.py"],
        "bucket": "d_win",
    },
    {
        "id": "soft19_contrast_text",
        "query": "where is the logic that complains if text is too hard to read against its background",
        "files_substr": ["accessibility.py"],
        "bucket": "miss_both",
    },
    {
        "id": "soft20_font_cohesive",
        "query": "how do we evaluate if the fonts used on the page are cohesive",
        "files_substr": ["fontsource/provider.py"],
        "bucket": "g_win",
    },
    {
        "id": "soft21_screen_reader",
        "query": "where is the expert that checks if screen readers can navigate the page",
        "files_substr": ["preflight.py"],
        "bucket": "tie",
    },
    {
        "id": "soft22_agent_commands",
        "query": "how are the agent commands actually registered and exposed to the user",
        "files_substr": ["agent_runner.py"],
        "bucket": "d_win",
    },
    {
        "id": "soft23_conversation_store",
        "query": "where do we store the data about an ongoing conversation or task",
        "files_substr": ["jobs/store.py"],
        "bucket": "d_win",
    },
    {
        "id": "soft24_retry_ok",
        "query": "what tells the system it's okay to retry an action if it fails the first time",
        "files_substr": ["policies/retry.py"],
        "bucket": "tie",
    },
    {
        "id": "soft25_cancel_clean",
        "query": "how do we stop everything cleanly if the user says to cancel the job",
        "files_substr": ["policies/cancellation.py", "cancellation.py"],
        "bucket": "g_win",
    },
    {
        "id": "soft26_idempotent_actions",
        "query": "where do we define which actions won't break things if we run them twice",
        "files_substr": ["actions/__init__.py"],
        "bucket": "tie",
    },
    {
        "id": "soft27_ui_library_pick",
        "query": "how do we pick the right user interface library based on what the project already uses",
        "files_substr": ["graph/interface.py"],
        "bucket": "tie",
    },
    {
        "id": "soft28_safe_icons",
        "query": "where do we search for icons that are safe to use commercially",
        "files_substr": ["import_verification/icons.py"],
        "bucket": "d_win",
    },
    {
        "id": "soft29_corporate_images",
        "query": "how does the system know which images are allowed for corporate projects",
        "files_substr": ["license/policy.py"],
        "bucket": "miss_both",
    },
    {
        "id": "soft30_animations",
        "query": "where do we find ready-to-use animations for buttons or loaders",
        "files_substr": ["extractors/motion.py"],
        "bucket": "d_win",
    },
]

SOFT_BLURB = (
    "Locked soft-30 from OpenCode agent A/B — natural-language queries only, "
    "no filenames in queries. Primary gate for agent-first retrieval R&D."
)
