# mcp_async_providers.py
from typing import Any, Dict

from fm_app.mcp_servers.db_meta import (
    db_meta_mcp_analyze_query,
    get_db_meta_mcp_prompt_items,
)
from fm_app.mcp_servers.db_ref import get_db_ref_prompt_items


class DbMetaAsyncProvider:
    name = "db-meta"

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
        text = await get_db_meta_mcp_prompt_items(
            req=req,
            flow_step_num=flow_step_num,
            settings=self.settings,
            logger=self.logger,
        )
        return {"db_meta_prompt_items": text}

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
