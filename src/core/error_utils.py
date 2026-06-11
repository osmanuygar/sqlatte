"""
Error handling utilities — prevent information disclosure via HTTP error details.

Instead of returning raw exception messages to clients (which leak stack traces,
file paths, and internal state), log the full error server-side and return an
opaque reference ID that can be used for log correlation.
"""
import uuid
import logging

from fastapi import HTTPException

logger = logging.getLogger("sqlatte.errors")


def server_error(exc: Exception, status_code: int = 500) -> HTTPException:
    """Return a safe HTTPException while logging the real cause server-side.

    Usage:
        except Exception as e:
            raise server_error(e)
    """
    error_id = str(uuid.uuid4())[:8].upper()
    logger.error("Internal error [%s]: %s", error_id, exc, exc_info=True)
    return HTTPException(
        status_code=status_code,
        detail=f"Internal server error [ID: {error_id}]",
    )
