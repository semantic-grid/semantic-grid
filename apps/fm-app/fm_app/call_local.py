import asyncio
import logging

from dotenv import load_dotenv

from fm_app.api.db_session import get_db
from fm_app.api.model import AddRequestModel, FlowType, WorkerRequest
from fm_app.db.db import add_request
from fm_app.workers.worker import wrk_add_request


async def main():
    load_dotenv(".env")
    async for db in get_db():
        user_request = AddRequestModel(
            request="Which wallets made their first MOBILE token transaction in the past 3 months?",  # noqa: E501
            flow=FlowType.openai_simple,
        )
        session_id = "067773fe-37ea-7fff-8000-05be8ca4f031"
        user_owner = "xb5BAhG27lP4nynqiT7mPAWRDnVN32qx@clients"

        (response, task_id) = await add_request(
            user_owner=user_owner, session_id=session_id, add_req=user_request, db=db
        )
        wrk_req = WorkerRequest(
            session_id=session_id,
            request_id=response.request_id,
            user=user_owner,
            request=response.request,
            response=response.response,
            status=response.status,
            flow=user_request.flow,
        )
        wrk_arg = wrk_req.model_dump(mode="json")
        task = wrk_add_request.apply_async(args=[wrk_arg], task_id=task_id)
        logging.info("Send task", extra={"action": "send_task", "task_id": task})


if __name__ == "__main__":
    asyncio.run(main())
