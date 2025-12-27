import asyncio
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fm_app.config import get_settings

settings = get_settings()
DATABASE_URL = f"postgresql+asyncpg://{settings.database_user}:{settings.database_pass}@{settings.database_server}:{settings.database_port}/{settings.database_db}"

# Track the engine per event loop to avoid "Future attached to different loop" errors
# Key is the event loop id, value is (engine, session_factory)
_engine_registry: dict[int, tuple[AsyncEngine, sessionmaker]] = {}
_registry_lock = asyncio.Lock()


async def _get_engine_for_current_loop() -> tuple[AsyncEngine, sessionmaker]:
    """
    Get or create an async engine bound to the current event loop.

    This ensures that each Celery task (which creates its own event loop)
    gets an engine that's properly bound to that loop, avoiding
    "Future attached to a different loop" errors.
    """
    loop = asyncio.get_running_loop()
    loop_id = id(loop)

    if loop_id in _engine_registry:
        return _engine_registry[loop_id]

    async with _registry_lock:
        # Double-check after acquiring lock
        if loop_id in _engine_registry:
            return _engine_registry[loop_id]

        # Create new engine for this event loop
        engine = create_async_engine(
            DATABASE_URL,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=360,
        )
        session_factory = sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        _engine_registry[loop_id] = (engine, session_factory)
        return engine, session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """Get a database session bound to the current event loop."""
    _, session_factory = await _get_engine_for_current_loop()
    async with session_factory() as session:
        yield session


async def dispose_engine_for_current_loop() -> None:
    """
    Dispose the engine for the current event loop.
    Call this when the event loop is about to be closed.
    """
    loop = asyncio.get_running_loop()
    loop_id = id(loop)

    if loop_id in _engine_registry:
        engine, _ = _engine_registry.pop(loop_id)
        await engine.dispose()


# For backward compatibility with code that imports engine/SESSION directly
# These will be lazily initialized on first use within the running event loop
_compat_engine: Optional[AsyncEngine] = None
_compat_session: Optional[sessionmaker] = None


def _get_compat_engine() -> AsyncEngine:
    """
    Get the compatibility engine (created on first access).
    WARNING: This is for backward compatibility only. Prefer using get_db().
    """
    global _compat_engine, _compat_session
    if _compat_engine is None:
        _compat_engine = create_async_engine(
            DATABASE_URL,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=360,
        )
        _compat_session = sessionmaker(
            bind=_compat_engine, class_=AsyncSession, expire_on_commit=False
        )
    return _compat_engine


def _get_compat_session() -> sessionmaker:
    """Get the compatibility session factory."""
    global _compat_session
    if _compat_session is None:
        _get_compat_engine()  # This initializes both
    return _compat_session


# Backward compatibility - these are now lazy properties
# Code importing `engine` or `SESSION` will still work but may have issues
# if used across different event loops
class _LazyEngine:
    """Lazy proxy for backward compatibility."""

    def __getattr__(self, name):
        return getattr(_get_compat_engine(), name)


class _LazySession:
    """Lazy proxy for backward compatibility."""

    def __call__(self, *args, **kwargs):
        return _get_compat_session()(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(_get_compat_session(), name)


engine = _LazyEngine()
SESSION = _LazySession()
