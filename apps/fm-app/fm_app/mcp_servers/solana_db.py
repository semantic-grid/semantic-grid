import csv
from datetime import datetime
from decimal import Decimal
from io import StringIO

from fastmcp import Context, FastMCP
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


class Settings(BaseSettings):
    database_user: str
    database_pass: str
    database_port: int
    database_server: str
    database_db: str
    database_wh_user: str
    database_wh_pass: str
    database_wh_port: int
    database_wh_port_new: int
    database_wh_port_v2: int
    database_wh_server: str
    database_wh_server_new: str
    database_wh_server_v2: str
    database_wh_params: str
    database_wh_params_new: str
    database_wh_params_v2: str
    database_wh_db: str
    database_wh_db_new: str
    database_wh_db_v2: str
    auth0_domain: str
    auth0_api_audience: str
    auth0_issuer: str
    auth0_algorithms: str
    log_level: str = "INFO"
    wrk_broker_connection: str = "pyamqp://guest@localhost//"
    dbmeta: str
    dbref: str
    irl_slots: str
    google_project_id: str
    google_cred_file: str
    google_llm_name: str = "gemini-1.5-pro-001"
    anthropic_api_key: str
    anthropic_llm_name: str = "claude-3-5-sonnet-20240620"
    openai_api_key: str
    openai_llm_name: str = "gpt-4o"
    deepseek_ai_api_url: str
    deepseek_ai_api_key: str
    deepseek_llm_name: str = "deepseek-chat"
    json_log: bool = True
    max_steps: int = 5
    guest_auth_host: str
    guest_auth_issuer: str


def sanitize_for_json(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    else:
        return obj


mcp = FastMCP(name="Solana DB", description="Solana DB MCP server")


@mcp.tool()
async def test(request: str, db: str, settings: Settings, context: Context) -> dict:
    """Test tool to check if the server is running."""
    # await context.log("info", f"Testing {request} {db}")
    return {"status": "ok"}


# Asynchronous tool
@mcp.tool()
async def fetch_data(
    request: str, db: str, settings: Settings, context: Context
) -> dict:
    """Retrieve data with SQL query."""
    await context.log(
        message=f"Querying {request} from {db}", level="info", logger_name="solana-db"
    )
    try:
        if db == "":
            database_url = f"{settings.databse_wh_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server}:{settings.database_wh_port}/{settings.database_wh_db}{settings.database_wh_params}"
            engine = create_engine(
                database_url,
                pool_size=40,
                max_overflow=60,
                pool_pre_ping=True,
                pool_recycle=360,
                connect_args={"application_name": "fm_app_mcp_wh"},
            )
            session = sessionmaker(bind=engine, expire_on_commit=False)
            database = session()

        elif db == "NWH":
            database_new_wh_url = f"{settings.database_wh_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server_new}:{settings.database_wh_port_new}/{settings.database_wh_db_new}{settings.database_wh_params_new}"
            engine_new_wh = create_engine(
                database_new_wh_url,
                pool_size=40,
                max_overflow=60,
                pool_pre_ping=True,
                pool_recycle=360,
                connect_args={"application_name": "fm_app_mcp_wh"},
            )
            session_new_wh = sessionmaker(bind=engine_new_wh, expire_on_commit=False)
            database = session_new_wh()

        elif db == "V2":
            database_v2_url = f"{settings.database_wh_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server_v2}:{settings.database_wh_port_v2}/{settings.database_wh_db_v2}{settings.database_wh_params_v2}"
            engine_v2 = create_engine(
                database_v2_url,
                pool_size=40,
                max_overflow=60,
                pool_pre_ping=True,
                pool_recycle=360,
                connect_args={"application_name": "fm_app_mcp_wh"},
            )
            session_v2 = sessionmaker(bind=engine_v2, expire_on_commit=False)
            database = session_v2()

        else:
            raise Exception(f"Unknown database: {db}")

        result = database.execute(text(request))
        data = result.mappings().fetchall()
        rows = [dict(row) for row in data]
        clean_rows = sanitize_for_json(rows)
        if len(rows) == 0:
            return {"csv": None, "rows": 0}
        if len(rows) > 1000:
            return {"csv": None, "rows": len(rows)}
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=clean_rows[0].keys())
        writer.writeheader()
        writer.writerows(clean_rows)

        csv_result = output.getvalue()
        output.close()
        await context.log(
            message=f"Produced CSV, rows={len(rows)}",
            level="info",
            logger_name="solana-db",
        )
        return {"csv": csv_result, "rows": len(rows), "raw_data": clean_rows}

    except Exception as e:
        return {"csv": None, "rows": 0, "error": str(e)}


@mcp.tool()
async def execute_sql(
    request: str, db: str, settings: Settings, context: Context
) -> dict:
    """Execute SQL query."""
    await context.log(
        message=f"Querying {request} from {db}", level="info", logger_name="solana-db"
    )
    try:
        if db == "":
            database_url = f"{settings.database_wh_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server}:{settings.database_wh_port}/{settings.database_wh_db}{settings.database_wh_params}"
            engine = create_engine(
                database_url,
                pool_size=40,
                max_overflow=60,
                pool_pre_ping=True,
                pool_recycle=360,
                connect_args={"application_name": "fm_app_mcp_wh"},
            )
            session = sessionmaker(bind=engine, expire_on_commit=False)
            database = session()

        elif db == "NWH":
            database_new_wh_url = f"{settings.database_wh_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server_new}:{settings.database_wh_port_new}/{settings.database_wh_db_new}{settings.database_wh_params_new}"
            engine_new_wh = create_engine(
                database_new_wh_url,
                pool_size=40,
                max_overflow=60,
                pool_pre_ping=True,
                pool_recycle=360,
                connect_args={"application_name": "fm_app_mcp_wh"},
            )
            session_new_wh = sessionmaker(bind=engine_new_wh, expire_on_commit=False)
            database = session_new_wh()

        elif db == "V2":
            database_v2_url = f"{settings.database_wh_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server_v2}:{settings.database_wh_port_v2}/{settings.database_wh_db_v2}{settings.database_wh_params_v2}"
            engine_v2 = create_engine(
                database_v2_url,
                pool_size=40,
                max_overflow=60,
                pool_pre_ping=True,
                pool_recycle=360,
                connect_args={"application_name": "fm_app_mcp_wh"},
            )
            session_v2 = sessionmaker(bind=engine_v2, expire_on_commit=False)
            database = session_v2()

        else:
            raise Exception(f"Unknown database: {db}")

        result = database.execute(text(request))
        data = result.mappings().fetchall()
        rows = [dict(row) for row in data]
        return {"rows": rows}

    except Exception as e:
        return {"csv": None, "rows": 0, "error": str(e)}


if __name__ == "__main__":
    # This code only runs when the file is executed directly

    # Basic run with default settings (stdio transport)
    mcp.run()

    # Or with specific transport and parameters
    # mcp.run(transport="sse", host="127.0.0.1", port=9000)
