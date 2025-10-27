import requests

from fm_app.api.model import GetPromptModel, McpServerRequest, PromptsSetModel


def get_db_ref_prompt_items(
    req: McpServerRequest, flow_step_num: int, settings, logger
):
    # Getting context from DBref service
    headers = {"Content-Type": "application/json", "Request-Id": str(req.request_id)}
    dbref_request = GetPromptModel(user_request=req.request)
    url = f"{settings.dbref}/api/v1/get_prompt_items"
    response = requests.post(url, headers=headers, json=dbref_request.model_dump())
    if response.status_code != 200:
        logger.error(
            "Filed to call dbref service",
            flow_stage="error",
            flow_step_num=flow_step_num,
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
