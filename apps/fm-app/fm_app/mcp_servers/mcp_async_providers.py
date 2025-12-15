# mcp_async_providers.py
from typing import Any, Dict, List, Optional

from fm_app.mcp_servers.db_meta import (
    db_meta_mcp_analyze_query,
    get_db_meta_database_overview,
    get_db_meta_mcp_prompt_items_v2,
)
from fm_app.mcp_servers.db_ref import get_db_ref_prompt_items

# Define item type presets for different slots/scenarios
MCP_ITEMS_FULL = ["DBStruct", "QueryExample", "Instruction", "SQLDialect"]
# Planner needs schema, examples, and domain instructions to understand data model
MCP_ITEMS_PLANNER = ["DBStruct", "QueryExample", "Instruction"]
# With approved plan: skip schema (plan has it), keep examples and instructions
MCP_ITEMS_WITH_PLAN = ["QueryExample", "Instruction", "SQLDialect"]


class DbMetaAsyncProvider:
    name = "db-meta"

    def __init__(self, settings, logger):
        self.settings = settings
        self.logger = logger

    async def vars_for_slot(
        self,
        slot: str,
        req_ctx: Dict[str, Any],
        items: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        req_ctx carries things like req, flow_step_num, etc.
        Returns small JSON-safe values to inject into Jinja.

        Args:
            slot: The slot name being rendered
            req_ctx: Request context with req, flow_step_num, etc.
            items: Optional list of item types to fetch. If None, uses slot defaults.
        """
        req = req_ctx["req"]
        flow_step_num = req_ctx.get("flow_step_num", 0)

        # For discovery slot, return database overview
        if slot == "discovery":
            text = await get_db_meta_database_overview(
                req=req,
                flow_step_num=flow_step_num,
                settings=self.settings,
                logger=self.logger,
            )
            return {"db_overview": text}

        # Determine which items to fetch based on:
        # 1. Explicit items parameter
        # 2. has_query_plan flag in req_ctx (skip schema if plan provides it)
        # 3. Slot-specific defaults
        has_query_plan = req_ctx.get("has_query_plan", False)

        if items is not None:
            fetch_items = items
        elif slot == "query_planner":
            fetch_items = MCP_ITEMS_PLANNER
        elif has_query_plan:
            # Plan already has relevant_schema, skip DBStruct
            fetch_items = MCP_ITEMS_WITH_PLAN
        else:
            fetch_items = MCP_ITEMS_FULL

        # Use v2 API for structured response
        result = await get_db_meta_mcp_prompt_items_v2(
            req=req,
            flow_step_num=flow_step_num,
            settings=self.settings,
            logger=self.logger,
            items=fetch_items,
        )

        return {"db_meta_prompt_items": result.combined_text}

    async def analyze_query(self, req_ctx: Dict[str, Any], sql: str) -> Dict[str, Any]:
        # Example if you want to use it for another slot or post-generation step
        res = await db_meta_mcp_analyze_query(
            req=req_ctx["req"],
            sql=sql,
            flow_step_num=req_ctx.get("flow_step_num", 0),
            settings=self.settings,
            logger=self.logger,
        )
        return res


class DbRefAsyncProvider:
    name = "db-ref"

    def __init__(self, settings, logger):
        self.settings = settings
        self.logger = logger

    async def vars_for_slot(self, slot: str, req_ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        req_ctx carries things like req, flow_step_num, etc.
        Returns small JSON-safe values to inject into Jinja.
        """
        req = req_ctx["req"]
        flow_step_num = req_ctx.get("flow_step_num", 0)

        # Call your existing function
        text = get_db_ref_prompt_items(
            req=req,
            flow_step_num=flow_step_num,
            settings=self.settings,
            logger=self.logger,
        )
        return {"db_ref_prompt_items": text}
