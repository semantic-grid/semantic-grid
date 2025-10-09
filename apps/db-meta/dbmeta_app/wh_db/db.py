from sqlalchemy import URL, create_engine, Engine

from dbmeta_app.config import get_settings


def get_db() -> Engine:
    settings = get_settings()

    url: URL = URL.create(
        drivername=settings.database_wh_driver,
        username=settings.database_wh_user,
        password=settings.database_wh_pass,
        host=settings.database_wh_server,
        port=settings.database_wh_port,
        database=settings.database_wh_db
    )
    url = url.update_query_string(settings.database_wh_params)

    return create_engine(
        url, pool_size=20, max_overflow=30, pool_pre_ping=True, pool_recycle=360
    )
