import requests

from fm_app.api.v1.model import GetPromptModel, McpServerRequest, PromptsSetModel


def get_db_ref_prompt_items(
    req: McpServerRequest, flow_step_num: int, settings, logger
):
    """
    Get prompt items from db-ref service.
    Returns empty string if service is unavailable or disabled.
    """
    try:
        # Getting context from DBref service
        headers = {
            "Content-Type": "application/json",
            "Request-Id": str(req.request_id),
        }
        dbref_request = GetPromptModel(user_request=req.request)
        url = f"{settings.dbref}/api/v1/get_prompt_items"

        # Use timeout to avoid hanging
        response = requests.post(
            url,
            headers=headers,
            json=dbref_request.model_dump(),
            timeout=5,  # 5 second timeout
        )

        if response.status_code != 200:
            logger.warning(
                "db-ref service returned non-200 status, continuing without it",
                flow_stage="dbref_unavailable",
                flow_step_num=flow_step_num,
                status_code=response.status_code,
            )
            return ""

        dbref_prompts = response.json()
        logger.info(
            "Got dbref prompts",
            flow_stage="got_dbref_prompts",
            flow_step_num=flow_step_num + 1,
            prompts=dbref_prompts,
        )
        dbref_prompts = PromptsSetModel.model_validate(dbref_prompts)
        dbref = [el.text for el in dbref_prompts.prompt_items]
        dbref = "\n".join(dbref)

        return dbref

    except requests.exceptions.Timeout:
        logger.warning(
            "db-ref service timeout, continuing without it",
            flow_stage="dbref_timeout",
            flow_step_num=flow_step_num,
        )
        return ""

    except requests.exceptions.ConnectionError:
        logger.warning(
            "db-ref service connection failed, continuing without it",
            flow_stage="dbref_connection_error",
            flow_step_num=flow_step_num,
        )
        return ""

    except Exception as e:
        logger.warning(
            "db-ref service failed with unexpected error, continuing without it",
            flow_stage="dbref_error",
            flow_step_num=flow_step_num,
            error=str(e),
        )
        return ""
