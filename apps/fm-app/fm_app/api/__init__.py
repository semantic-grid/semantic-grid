"""
Flow Manager API package.

This package contains two API versions:
- v1: Legacy request-response architecture (default for backward compatibility)
- v2: Flexible message-based architecture

For backward compatibility, v1 models and routes are re-exported at the top level.
New code should explicitly import from v1 or v2 submodules.
"""

# Re-export v1 for backward compatibility
# Shared utilities (not version-specific)
from fm_app.api.auth0 import (  # noqa: F401
    UnauthenticatedException,
    UnauthorizedException,
    VerifyGuestToken,
    VerifyToken,
)
from fm_app.api.db_session import (  # noqa: F401
    engine,
    get_db,
    get_wh_db,
    wh_engine,
)
from fm_app.api.v1 import *  # noqa: F403, F401

__all__ = [
    # Shared auth utilities
    "UnauthorizedException",
    "UnauthenticatedException",
    "VerifyToken",
    "VerifyGuestToken",
    # Shared DB utilities
    "get_db",
    "get_wh_db",
    "engine",
    "wh_engine",
]
