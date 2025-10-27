from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

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


WH_URL = f"{settings.database_wh_driver}://{settings.database_wh_user}:{settings.database_wh_pass}@{settings.database_wh_server_v2}:{settings.database_wh_port_v2}/{settings.database_wh_db_v2}{settings.database_wh_params_v2}"
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
