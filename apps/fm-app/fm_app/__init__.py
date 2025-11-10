import logging.config

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fm_app.api.db_session import engine
from fm_app.api.v1.routes import api_router
from fm_app.api.v2.routes import api_router_v2
from fm_app.logs import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)
LOGGER = logging.getLogger("fm_app")

app = FastAPI(
    version="v1",
    docs_url="/swagger",
    redoc_url="/redocs",
)

# Add the CORS middleware BEFORE routers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
app.include_router(api_router_v2, prefix="/api/v2")


@app.on_event("startup")
async def on_startup():
    """Application startup - initialize background tasks."""
    print("Starting fm_app...")

    # Start timeout monitor for v2 messages
    from fm_app.workers.v2.timeout_monitor import start_monitor

    try:
        await start_monitor()
        print("V2 timeout monitor started")
    except Exception as e:
        LOGGER.error(f"Failed to start timeout monitor: {e}")
        # Don't fail startup if monitor fails to start


@app.on_event("shutdown")
async def on_shutdown():
    """Application shutdown - cleanup background tasks."""
    print("Shutting down fm_app...")

    # Stop timeout monitor
    from fm_app.workers.v2.timeout_monitor import stop_monitor

    try:
        await stop_monitor()
        print("V2 timeout monitor stopped")
    except Exception as e:
        LOGGER.error(f"Failed to stop timeout monitor: {e}")

    # Close database connections
    await engine.dispose()
    print("fm_app shutdown complete")
