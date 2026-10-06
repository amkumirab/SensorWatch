from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from sensorwatch.config import digest_api_key, get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_ingest_api_key(
    provided_key: Annotated[str | None, Security(api_key_header)],
) -> None:
    """Require the configured ingestion key while allowing opt-in authentication."""
    expected_digest = get_settings().ingest_api_key_digest
    if expected_digest is None:
        return

    valid = (
        provided_key is not None
        and len(provided_key) <= 512
        and hmac.compare_digest(digest_api_key(provided_key), expected_digest)
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
