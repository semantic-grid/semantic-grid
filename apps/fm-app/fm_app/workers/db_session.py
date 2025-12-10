from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fm_app.config import get_settings

settings = get_settings()
DATABASE_URL = f"postgresql+asyncpg://{settings.database_user}:{settings.database_pass}@{settings.database_server}:{settings.database_port}/{settings.database_db}"

engine = create_async_engine(
    DATABASE_URL,
    pool_size=3,  # Smaller pool for worker processes
    max_overflow=7,  # Allow burst to 10 total connections per worker
    pool_pre_ping=True,  # Verify connections before use
    pool_recycle=300,  # Recycle idle connections after 5 minutes
    pool_timeout=30,  # Fail fast if no connections available
    connect_args={
        "server_settings": {"application_name": "fm_app_celery"},
    },
)

SESSION = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SESSION() as session:
        yield session
