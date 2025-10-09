from sqlalchemy import URL, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, Session

from fm_app.config import get_settings

settings = get_settings()

DATABASE_URL = f"postgresql+asyncpg://{settings.database_user}:{settings.database_pass}@{settings.database_server}:{settings.database_port}/{settings.database_db}"

engine = create_async_engine(
    DATABASE_URL, pool_size=20, max_overflow=30, pool_pre_ping=True, pool_recycle=360
)

SESSION = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with SESSION() as session:
        yield session


WH_URL: URL = URL.create(
    drivername=settings.database_wh_driver,
    username=settings.database_wh_user,
    password=settings.database_wh_pass,
    host=settings.database_wh_server,
    port=settings.database_wh_port,
    database=settings.database_wh_db
)
WH_URL = WH_URL.update_query_string(settings.database_wh_params)

wh_engine = create_engine(
    WH_URL,
    pool_size=40,
    max_overflow=60,
    pool_pre_ping=True,
    pool_recycle=360,
)

wh_session = sessionmaker(bind=wh_engine, expire_on_commit=False)


def get_wh_db() -> Session:
    session = wh_session()
    return session
