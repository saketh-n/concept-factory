"""Agent driver for Concept Factory.

Each topic card gets its own subfolder under ``workspace/`` and its own
headless **Grok Build** instance. We never point the agent at the meta-agent
template folder (that would blow up token usage across ~100 parallel runs);
instead the house style is condensed into the prompts module.

This package is a *pure driver*: it knows how to run the Grok CLI and build
prompts. Topic state lives in main.py; global driver settings live in
``settings.json`` next to this package.

Claude Code was removed as a selectable factory driver; stale
``driver: "claude"`` settings coerce to Grok on load/save.

The package re-exports the full public surface so callers keep using
``import agent; agent.X``. Tests that patch internals target the submodule
whose function actually looks the name up (e.g. ``agent.driver.run_grok``).
"""
from . import catalog, driver, gates, gitops, paths, prompts, settings, workspace, xai  # noqa: F401

from .paths import (  # noqa: F401
    BACKEND_DIR,
    REPO_ROOT,
    SETTINGS_FILE,
    TEMPLATE_DIR,
    USAGE_FILE,
    WORKSPACE,
)
from .settings import (  # noqa: F401
    _BUDGET_UNSET,
    DEFAULT_SETTINGS,
    DRIVER_GROK,
    DRIVERS,
    GROK_BIN,
    TOKENS_PER_USD,
    default_settings,
    dollars_to_budget_tokens,
    format_budget_usd_for_storage,
    format_grok_goal_prompt,
    load_settings,
    normalize_settings,
    parse_budget_usd,
    resolve_build_budget_tokens,
    save_settings,
)
from .catalog import (  # noqa: F401
    CATALOG_CLI_TIMEOUT,
    CATALOG_TTL_SECONDS,
    apply_cli_current_to_settings,
    clear_settings_catalog_cache,
    cli_sync_enabled,
    current_models_signature,
    discover_grok_options,
    discover_settings_catalog,
    get_cli_help,
    get_cli_spawn_count,
    get_settings_catalog,
    parse_grok_models_output,
    parse_help_effort_levels,
    parse_help_possible_values,
    read_current_models,
    reset_cli_spawn_count,
    resolve_model_selection,
    run_discovery_cli,
    sync_settings_to_cli,
    update_catalog_cache_current,
)
from .workspace import (  # noqa: F401
    PLAN_FILE,
    copy_template,
    dist_base_ok,
    is_built,
    seed_history,
    slugify,
    topic_dir,
)
from .gitops import (  # noqa: F401
    git_commit,
    git_log,
    git_revert_to,
    has_committed_dist,
    served_hash,
)
from .prompts import (  # noqa: F401
    build_plan_prompt,
    build_prompt,
    consolidate_prompt,
    improve_prompt,
    plan_title,
    refine_prompt,
)
from .driver import (  # noqa: F401
    BUILD_TIMEOUT,
    CONCURRENCY,
    EXECUTOR,
    PLAN_TIMEOUT,
    build_driver_cmd,
    build_grok_cmd,
    run_agent,
    run_grok,
)
from .gates import (  # noqa: F401
    GATE_TIMEOUT,
    finalize_build,
    patch_router_basename,
    run_lint_gate,
    run_validator_gate,
)
from .xai import (  # noqa: F401
    CHAT_MODEL,
    chat_system_prompt,
    get_balance,
    set_budget_usd,
    stream_chat,
    ticks_to_usd,
    topic_context,
)
